// SPDX-License-Identifier: GPL-3.0-or-later
// Independent JACK output gain, or an always-on session observer with --channels 0.
#define _POSIX_C_SOURCE 200809L
#include <jack/jack.h>
#include <math.h>
#include <poll.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#define MAX_CHANNELS 64
_Static_assert(ATOMIC_INT_LOCK_FREE == 2, "control exchange must be lock-free");
static jack_client_t *client;
static jack_port_t *inputs[MAX_CHANNELS], *outputs[MAX_CHANNELS];
static unsigned channels;
static atomic_uint level = 100, xruns;
static atomic_bool alive = 1;
static float gain = 1;
static volatile sig_atomic_t stopping;
static void stop(int sig) { (void)sig; stopping = 1; }
static void shutdown_server(void *arg) { (void)arg; atomic_store(&alive, 0); }
static int xrun(void *arg) { (void)arg; atomic_fetch_add(&xruns, 1); return 0; }
static int process(jack_nframes_t frames, void *arg) {
    (void)arg;
    if (!channels) return 0;
    const float target = atomic_load_explicit(&level, memory_order_relaxed) / 100.f;
    const float step = 1.f / (jack_get_sample_rate(client) * 0.01f);
    const float *in[MAX_CHANNELS];
    float *out[MAX_CHANNELS];
    for (unsigned c = 0; c < channels; ++c) {
        in[c] = jack_port_get_buffer(inputs[c], frames);
        out[c] = jack_port_get_buffer(outputs[c], frames);
    }
    for (jack_nframes_t n = 0; n < frames; ++n) {
        gain += fminf(step, fmaxf(-step, target - gain));
        for (unsigned c = 0; c < channels; ++c)
            out[c][n] = isfinite(in[c][n]) ? in[c][n] * gain : 0.f;
    }
    return 0;
}
int main(int argc, char **argv) {
    const char *name = "level_dac_out";
    channels = 2;
    for (int n = 1; n < argc; ++n) {
        const char *key = argv[n];
        if (++n >= argc) return 2;
        if (!strcmp(key, "--client")) name = argv[n];
        else if (!strcmp(key, "--channels") || !strcmp(key, "--level")) {
            char *end;
            long value = strtol(argv[n], &end, 10);
            if (!*argv[n] || *end || value < 0) return 2;
            if (!strcmp(key, "--channels")) {
                if (value > MAX_CHANNELS) return 2;
                channels = value;
            } else {
                if (value > 100) return 2;
                atomic_store(&level, value);
            }
        } else return 2;
    }
    gain = atomic_load(&level) / 100.f;
    jack_status_t status;
    const char *server = getenv("JACK_DEFAULT_SERVER");
    client = jack_client_open(name, JackNoStartServer | JackUseExactName | (server ? JackServerName : 0), &status, server);
    if (!client) return 1;
    for (unsigned c = 0; c < channels; ++c) {
        char port[32];
        snprintf(port, sizeof port, "playback_%u", c + 1);
        inputs[c] = jack_port_register(client, port, JACK_DEFAULT_AUDIO_TYPE, JackPortIsInput, 0);
        snprintf(port, sizeof port, "capture_%u", c + 1);
        outputs[c] = jack_port_register(client, port, JACK_DEFAULT_AUDIO_TYPE, JackPortIsOutput, 0);
        if (!inputs[c] || !outputs[c]) { jack_client_close(client); return 1; }
    }
    jack_on_shutdown(client, shutdown_server, NULL);
    jack_set_xrun_callback(client, xrun, NULL);
    jack_set_process_callback(client, process, NULL);
    signal(SIGINT, stop); signal(SIGTERM, stop);
    if (jack_activate(client)) { jack_client_close(client); return 1; }
    setvbuf(stdout, NULL, _IOLBF, 0);
    struct pollfd control = {.fd = channels ? STDIN_FILENO : -1, .events = POLLIN};
    char line[64];
    int overflow = 0;
    unsigned used = 0, previous_xruns = ~0u, ticks = 20;
    while (!stopping && atomic_load(&alive)) {
        int ready = poll(&control, 1, 50);
        if (ready > 0 && (control.revents & (POLLIN | POLLHUP))) {
            char bytes[128];
            ssize_t size = read(STDIN_FILENO, bytes, sizeof bytes);
            if (size == 0) break;  // the controlling daemon has gone
            for (ssize_t n = 0; n < size; ++n) {
                if (bytes[n] == '\n') {
                    line[used] = 0;
                    char *end;
                    long value = strtol(line, &end, 10);
                    if (!overflow && used && !*end && value >= 0 && value <= 100) atomic_store(&level, value);
                    used = 0; overflow = 0;
                } else if (!overflow && used < sizeof line - 1) line[used++] = bytes[n];
                else overflow = 1;
            }
        }
        unsigned errors = atomic_load(&xruns);
        if (++ticks >= 20 || errors != previous_xruns) {
            printf("{\"event\":\"status\",\"xruns\":%u,\"rate\":%u,\"period\":%u,\"dsp_load\":%.3f,\"level\":%u}\n",
                   errors, jack_get_sample_rate(client), jack_get_buffer_size(client), jack_cpu_load(client),
                   atomic_load(&level));
            ticks = 0; previous_xruns = errors;
        }
    }
    jack_client_close(client);
    return 0;
}
