// SPDX-License-Identifier: GPL-3.0-or-later
// An isolated test source. Connects only to the explicitly named dummy JACK server.
#define _POSIX_C_SOURCE 200809L
#include <jack/jack.h>
#include <math.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

static jack_port_t *ports[3];
static unsigned frame;
static unsigned rate;
static volatile sig_atomic_t stopped;
static void stop(int signal) { (void)signal; stopped = 1; }
static int process(jack_nframes_t frames, void *arg) {
    (void)arg;
    float *buffers[3];
    const float scale[3] = {0.25f, 0.5f, 1.25f};
    for (int p = 0; p < 3; ++p) buffers[p] = jack_port_get_buffer(ports[p], frames);
    for (jack_nframes_t n = 0; n < frames; ++n) {
        float value = sinf((float)(6.283185307179586 * 1000 * frame / rate));
        frame = (frame + 1) % rate;
        for (int p = 0; p < 3; ++p) buffers[p][n] = scale[p] * value;
    }
    return 0;
}
int main(void) {
    const char *server = getenv("JACK_DEFAULT_SERVER");
    if (!server) return 2;
    jack_status_t status;
    jack_client_t *client = jack_client_open("meter_test_tone", JackNoStartServer | JackServerName, &status, server);
    if (!client) return 1;
    rate = jack_get_sample_rate(client);
    for (int p = 0; p < 3; ++p) {
        char name[8];
        snprintf(name, sizeof name, "out_%d", p + 1);
        ports[p] = jack_port_register(client, name, JACK_DEFAULT_AUDIO_TYPE, JackPortIsOutput, 0);
        if (!ports[p]) return 1;
    }
    jack_set_process_callback(client, process, NULL);
    if (jack_activate(client)) return 1;
    if (jack_connect(client, "meter_test_tone:out_2", "system:playback_1")) return 1;
    signal(SIGTERM, stop);
    signal(SIGINT, stop);
    while (!stopped) pause();
    jack_client_close(client);
    return 0;
}
