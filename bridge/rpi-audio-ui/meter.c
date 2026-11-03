// SPDX-License-Identifier: GPL-3.0-or-later
// Passive peak taps. Only reads samples in the JACK callback; JSON and graph queries run on the main thread.
// JACK API: https://jackaudio.org/api/group__PortFunctions.html
#define _POSIX_C_SOURCE 200809L
#include <jack/jack.h>
#include <math.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define MAX_PORTS 128
#define MAX_GROUPS 66
_Static_assert(ATOMIC_INT_LOCK_FREE == 2, "peak exchange must be lock-free");

typedef struct {
    jack_port_t *port;
    const char *source;
    int group;
} Tap;

static Tap taps[MAX_PORTS];
static int count;
static atomic_uint peaks[MAX_GROUPS];
static const char *groups[MAX_GROUPS] = {"in", "out"};
static int group_count = 2;
static atomic_uint xruns;
static atomic_uint cycles;
static atomic_bool alive = 1;
static volatile sig_atomic_t stopping;

static void stop_signal(int sig) { (void)sig; stopping = 1; }
static void shutdown_server(void *arg) { (void)arg; atomic_store(&alive, 0); }
static int xrun(void *arg) { (void)arg; atomic_fetch_add(&xruns, 1); return 0; }
static void quiet(const char *text) { (void)text; }

static int process(jack_nframes_t frames, void *arg) {
    (void)arg;
    float peak[MAX_GROUPS] = {0, 0};
    for (int p = 0; p < count; ++p) {
        const float *samples = jack_port_get_buffer(taps[p].port, frames);
        if (!samples) continue;
        for (jack_nframes_t n = 0; n < frames; ++n) {
            float value = fabsf(samples[n]);
            if (isfinite(value) && value > peak[taps[p].group]) peak[taps[p].group] = value;
        }
    }
    for (int g = 0; g < group_count; ++g) {
        uint32_t bits;
        memcpy(&bits, &peak[g], sizeof bits);
        unsigned previous = atomic_load_explicit(&peaks[g], memory_order_relaxed);
        while (bits > previous && !atomic_compare_exchange_weak_explicit(
                &peaks[g], &previous, bits, memory_order_relaxed, memory_order_relaxed)) {}
    }
    atomic_fetch_add_explicit(&cycles, 1, memory_order_relaxed);
    return 0;
}

static int contains(const char **names, const char *name) {
    if (names) for (int n = 0; names[n]; ++n) if (!strcmp(names[n], name)) return 1;
    return 0;
}

static void reconcile(jack_client_t *client, int available[MAX_GROUPS]) {
    memset(available, 0, MAX_GROUPS * sizeof *available);
    for (int p = 0; p < count; ++p) {
        Tap *tap = &taps[p];
        const char *destination = jack_port_name(tap->port);
        jack_port_t *source = jack_port_by_name(client, tap->source);
        const char *single[2] = {NULL, NULL};
        const char **allocated = NULL, **wanted = single;
        if (source && !strcmp(jack_port_type(source), JACK_DEFAULT_AUDIO_TYPE)) {
            if (jack_port_flags(source) & JackPortIsOutput) single[0] = tap->source;
            else wanted = allocated = jack_port_get_all_connections(client, source);
        }
        const char **existing = jack_port_get_all_connections(client, tap->port);
        if (existing) for (int n = 0; existing[n]; ++n)
            if (!contains(wanted, existing[n])) jack_disconnect(client, existing[n], destination);
        if (wanted) for (int n = 0; wanted[n]; ++n) {
            if (!contains(existing, wanted[n])) jack_connect(client, wanted[n], destination);
            if (jack_port_connected_to(tap->port, wanted[n])) ++available[tap->group];
        }
        if (existing) jack_free(existing);
        if (allocated) jack_free(allocated);
    }
}

int main(int argc, char **argv) {
    if (argc < 2 || argc > MAX_PORTS + 1) return 2;
    count = argc - 1;
    for (int p = 0; p < count; ++p) {
        char *arg = argv[p + 1], *equal = strchr(arg, '=');
        if (!equal) return 2;
        *equal = 0;
        if (strcmp(arg, "in") && strcmp(arg, "out")) {
            char *end;
            long number = strtol(arg + 1, &end, 10);
            if (arg[0] != 'p' || !arg[1] || *end || number < 0 || number > 63) return 2;
        }
        int group = 0;
        while (group < group_count && strcmp(groups[group], arg)) ++group;
        if (group == group_count) {
            if (group_count >= MAX_GROUPS) return 2;
            groups[group_count++] = arg;
        }
        taps[p].source = equal + 1;
        taps[p].group = group;
        if (!*taps[p].source) return 2;
    }
    signal(SIGINT, stop_signal);
    signal(SIGTERM, stop_signal);
    jack_set_error_function(quiet);
    jack_set_info_function(quiet);
    jack_status_t status;
    const char *server = getenv("JACK_DEFAULT_SERVER");
    jack_client_t *client = jack_client_open("rpi_audio_meter", JackNoStartServer | (server ? JackServerName : 0),
                                           &status, server);
    if (!client) return 1;
    for (int p = 0; p < count; ++p) {
        char name[24];
        snprintf(name, sizeof name, "tap_%d", p + 1);
        taps[p].port = jack_port_register(client, name, JACK_DEFAULT_AUDIO_TYPE, JackPortIsInput, 0);
        if (!taps[p].port) { jack_client_close(client); return 1; }
    }
    jack_on_shutdown(client, shutdown_server, NULL);
    jack_set_xrun_callback(client, xrun, NULL);
    if (jack_set_process_callback(client, process, NULL) || jack_activate(client)) {
        jack_client_close(client);
        return 1;
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    int available[MAX_GROUPS] = {0, 0}, iteration = 0;
    unsigned previous_cycle = 0;
    const struct timespec interval = {.tv_sec = 0, .tv_nsec = 200000000};
    while (!stopping && atomic_load(&alive)) {
        if (iteration++ % 5 == 0) reconcile(client, available);
        nanosleep(&interval, NULL);
        if (stopping || !atomic_load(&alive)) break;
        float values[MAX_GROUPS];
        unsigned cycle = atomic_load_explicit(&cycles, memory_order_relaxed);
        int fresh = cycle != previous_cycle;
        previous_cycle = cycle;
        for (int g = 0; g < group_count; ++g) {
            uint32_t bits = atomic_exchange_explicit(&peaks[g], 0, memory_order_relaxed);
            memcpy(&values[g], &bits, sizeof bits);
        }
        if (printf("{") < 0) break;
        for (int g = 0; g < group_count; ++g) {
            printf("%s\"%s\":", g ? "," : "", groups[g]);
            if (available[g] && fresh) printf("%.8g", values[g]); else printf("null");
        }
        if (printf(",\"_xruns\":%u,\"_rate\":%u,\"_period\":%u,\"_dsp_load\":%.3f}\n",
                   atomic_load(&xruns), jack_get_sample_rate(client), jack_get_buffer_size(client),
                   jack_cpu_load(client)) < 0) break;
    }
    jack_client_close(client);
    return 0;
}
