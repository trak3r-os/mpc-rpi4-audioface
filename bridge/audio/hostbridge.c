// SPDX-License-Identifier: GPL-3.0-or-later
// rpi-audio-hostbridge: one direction of the USB gadget's audio as a JACK client, for hub mode,
// where JACK runs on a local clock and the gadget on the USB host's.
//
//   rpi-audio-hostbridge --client NAME --device hw:CARD=UAC2Gadget --direction capture|playback
//                        --rate HZ --channels N [--margin-us 1500] [--quality 32]
//
// capture:  gadget -> JACK, ports NAME:capture_1..N   (what the host plays)
// playback: JACK -> gadget, ports NAME:playback_1..N  (what the host records)
//
// Everything happens in JACK's realtime callback: it reads or writes the gadget's ALSA buffer
// in place (mmap, never blocking) and resamples between the two clocks. There is no thread or
// queue of its own, so the only buffering is the ALSA buffer itself, held at --margin-us by
// steering the resampler's ratio. The delay added per direction is that margin plus the
// filter's --quality input frames, next to the JACK period every client has.
//
// The streams never stop on an underrun or overrun (stop threshold at the boundary): a late
// cycle gives the host silence at the right rate instead of a stalled stream, and the bridge
// jumps back to its margin (a "resync" in the status line, one JSON object per second).
#define _POSIX_C_SOURCE 200809L
#define _DEFAULT_SOURCE
#include <alsa/asoundlib.h>
#include <jack/jack.h>
#include <signal.h>
#include <stdatomic.h>
#include <stdio.h>
#include <sys/mman.h>
#include <unistd.h>

#include "hostbridge_core.h"

#define MAX_ERRORS 10        // ALSA errors in a row before giving up (the service starts us again)

static jack_client_t *client;
static jack_port_t *ports[HB_MAX_CHANNELS];
static snd_pcm_t *pcm;
static int capture;
static unsigned channels, rate, jack_rate, period, format, frame_bytes;
static unsigned margin, tolerance;       // gadget frames
static snd_pcm_uframes_t buffer;
static double nominal_step, step;
static hb_resampler resampler;
static hb_loop loop;
static float *scratch;                   // interleaved frames between the resampler and the other side
static unsigned scratch_frames;
static int running, trimming, errors_in_a_row;

static volatile sig_atomic_t stopping;
static atomic_int failed;                // an errno, or -1 for "JACK changed under us"
static atomic_bool server_alive = 1;
static atomic_uint resyncs, alsa_errors, cycles;
static atomic_int state, fill_min = INT32_MAX, fill_max = INT32_MIN, late_max, ppm10;
static atomic_long fill_sum;

static void on_signal(int sig) { (void)sig; stopping = 1; }
static void on_shutdown(void *arg) { (void)arg; atomic_store(&server_alive, 0); }
static int on_change(jack_nframes_t value, void *arg) {
    (void)arg;
    if (value != *(unsigned *)arg) atomic_store(&failed, -1);
    return 0;
}

// Gadget frames that went by since this JACK cycle began: the fill is judged as it was then,
// so that running late in a cycle is not read as a clock offset.
static double lateness(void) {
    jack_nframes_t frames;
    jack_time_t current, next;
    float period_us;
    if (jack_get_cycle_times(client, &frames, &current, &next, &period_us)) return 0;
    const jack_time_t now = jack_get_time();
    double us = now > current ? (double)(now - current) : 0;
    if (us > 2.0 * period_us) us = 2.0 * period_us;
    const int whole = (int)us;
    if (whole > atomic_load_explicit(&late_max, memory_order_relaxed))
        atomic_store_explicit(&late_max, whole, memory_order_relaxed);
    return us * 1e-6 * rate;
}

static void note_fill(double fill) {
    const int whole = (int)lrint(fill);
    if (whole < atomic_load_explicit(&fill_min, memory_order_relaxed))
        atomic_store_explicit(&fill_min, whole, memory_order_relaxed);
    if (whole > atomic_load_explicit(&fill_max, memory_order_relaxed))
        atomic_store_explicit(&fill_max, whole, memory_order_relaxed);
    atomic_fetch_add_explicit(&fill_sum, whole, memory_order_relaxed);
    atomic_fetch_add_explicit(&cycles, 1, memory_order_relaxed);
}

static void set_running(int on) {
    running = on;
    atomic_store_explicit(&state, on, memory_order_relaxed);
}

static void resync(void) {
    atomic_fetch_add_explicit(&resyncs, 1, memory_order_relaxed);
    hb_loop_resync(&loop);
}

// An error from the device: prepare and start it again, and line up from scratch. False when
// that fails or keeps happening; the callback then goes quiet and main() exits.
static int recover(long error) {
    atomic_fetch_add_explicit(&alsa_errors, 1, memory_order_relaxed);
    set_running(0);
    if (error == -ENODEV || ++errors_in_a_row > MAX_ERRORS ||
        snd_pcm_prepare(pcm) < 0 || snd_pcm_start(pcm) < 0) {
        atomic_store(&failed, error ? (int)-error : EIO);
        return 0;
    }
    return 1;
}

// Moves `frames` through the gadget's buffer in place. data: interleaved floats to read into
// or write from; NULL discards (capture) or writes silence (playback). Returns the frames done.
static unsigned transfer(float *data, unsigned frames) {
    unsigned done = 0;
    for (int turn = 0; done < frames && turn < 8; ++turn) {
        const snd_pcm_channel_area_t *areas;
        snd_pcm_uframes_t offset, chunk = frames - done;
        if (snd_pcm_mmap_begin(pcm, &areas, &offset, &chunk) < 0 || !chunk) break;
        char *at = (char *)areas[0].addr + areas[0].first / 8 + offset * frame_bytes;
        if (capture) {
            if (data) hb_to_float(at, data + (size_t)done * channels, chunk * channels, (int)format);
        } else if (data) {
            hb_from_float(data + (size_t)done * channels, at, chunk * channels, (int)format);
        } else {
            memset(at, 0, chunk * frame_bytes);
        }
        const snd_pcm_sframes_t committed = snd_pcm_mmap_commit(pcm, offset, chunk);
        if (committed <= 0) break;
        done += (unsigned)committed;
    }
    return done;
}

static void silence(jack_nframes_t frames) {
    for (unsigned c = 0; c < channels; ++c)
        memset(jack_port_get_buffer(ports[c], frames), 0, sizeof(float) * frames);
}

static int process_capture(jack_nframes_t frames, void *arg) {
    (void)arg;
    if (atomic_load_explicit(&failed, memory_order_relaxed) || frames > scratch_frames) {
        silence(frames);
        return 0;
    }
    snd_pcm_sframes_t avail = snd_pcm_avail(pcm);
    if (avail < 0) {
        recover(avail);
        silence(frames);
        return 0;
    }
    errors_in_a_row = 0;
    const double late = lateness();
    double next_step = step;
    unsigned need = hb_need(&resampler, frames, step);
    if (!running) {
        // Wait until a cycle's input and the margin are there, drop anything older, and go.
        const long want = (long)need + margin + lrint(late);
        if (avail < want) {
            silence(frames);
            return 0;
        }
        transfer(NULL, (unsigned)(avail - want));
        hb_loop_resync(&loop);
        next_step = nominal_step * loop.correction;
        set_running(1);
    } else if ((unsigned long)avail < need) {
        // The host fell behind (or stopped): nothing to play this cycle.
        set_running(0);
        resync();
        silence(frames);
        return 0;
    } else {
        const double left = (double)avail - late - need;   // what stays buffered, as of the cycle's start
        note_fill(left);
        if (left - margin > tolerance) {
            // Far too much buffered (we missed a cycle): drop it at once rather than play fast for seconds.
            transfer(NULL, (unsigned)(left - margin));
            resync();
            next_step = nominal_step * loop.correction;
        } else {
            next_step = nominal_step * hb_loop_update(&loop, (left - margin) / rate, (double)frames / jack_rate);
        }
    }
    float *in = hb_append(&resampler, need);
    if (!in) {   // cannot happen: the resampler was sized for a whole period
        set_running(0);
        silence(frames);
        return 0;
    }
    const unsigned got = transfer(in, need);
    if (got < need) memset(in + (size_t)got * channels, 0, sizeof(float) * (need - got) * channels);
    hb_process(&resampler, frames, step, scratch);
    for (unsigned c = 0; c < channels; ++c) {
        float *out = jack_port_get_buffer(ports[c], frames);
        const float *from = scratch + c;
        for (jack_nframes_t n = 0; n < frames; ++n) out[n] = from[(size_t)n * channels];
    }
    step = next_step;
    atomic_store_explicit(&ppm10, (int)lrint((loop.correction - 1) * 1e7), memory_order_relaxed);
    return 0;
}

static int process_playback(jack_nframes_t frames, void *arg) {
    (void)arg;
    if (atomic_load_explicit(&failed, memory_order_relaxed)) return 0;
    const snd_pcm_sframes_t avail = snd_pcm_avail(pcm);
    if (avail < 0) {
        recover(avail);
        return 0;
    }
    errors_in_a_row = 0;
    const double late = lateness();
    const long fill = (long)buffer - avail;        // frames queued for the host; negative after an underrun
    const double at_start = fill + late;           // the same, as of the cycle's start
    double next_step = step;
    unsigned skip = 0;

    float *in = hb_append(&resampler, frames);
    if (!in) {
        atomic_store(&failed, -1);
        return 0;
    }
    for (unsigned c = 0; c < channels; ++c) {
        const float *from = jack_port_get_buffer(ports[c], frames);
        float *to = in + c;
        for (jack_nframes_t n = 0; n < frames; ++n) to[(size_t)n * channels] = from[n];
    }
    unsigned made = hb_ready(&resampler, step);
    if (made > scratch_frames) made = scratch_frames;
    hb_process(&resampler, made, step, scratch);

    if (!running || fill < 0) {
        // Starting, or the host ran out of our audio (it got silence meanwhile): put the margin back.
        double target = margin - late;
        if (target < margin / 4.0) target = margin / 4.0;
        transfer(NULL, (unsigned)lrint(target - (double)fill));
        if (running) resync();
        else hb_loop_resync(&loop);
        next_step = nominal_step * loop.correction;
        set_running(1);
        trimming = 0;
    } else {
        note_fill(at_start);
        if (at_start - margin > tolerance) {
            // Far too much queued (the host stalled): leave out the excess instead of playing slow for seconds.
            skip = (unsigned)(at_start - margin);
            if (skip > made) skip = made;
            if (!trimming) resync();
            trimming = 1;
            next_step = nominal_step * loop.correction;
        } else {
            trimming = 0;
            next_step = nominal_step * hb_loop_update(&loop, (at_start - margin) / rate, (double)frames / jack_rate);
        }
    }
    transfer(scratch + (size_t)skip * channels, made - skip);
    step = next_step;
    atomic_store_explicit(&ppm10, (int)lrint((loop.correction - 1) * 1e7), memory_order_relaxed);
    return 0;
}

static int fail(const char *what, int error) {
    fprintf(stderr, "rpi-audio-hostbridge: %s: %s\n", what, error < 0 ? snd_strerror(error) : "failed");
    return 1;
}

// Opens the device for in-place access at its own format. wanted: the least buffer in frames.
static int open_device(const char *device, snd_pcm_uframes_t wanted) {
    static const snd_pcm_format_t formats[] = {SND_PCM_FORMAT_S32_LE, SND_PCM_FORMAT_S24_3LE, SND_PCM_FORMAT_S16_LE};
    static const unsigned sizes[] = {HB_S32, HB_S24_3, HB_S16};
    snd_pcm_hw_params_t *hw;
    snd_pcm_sw_params_t *sw;
    snd_pcm_uframes_t boundary, size = wanted * 2 > 1024 ? wanted * 2 : 1024, chunk;
    int error = snd_pcm_open(&pcm, device, capture ? SND_PCM_STREAM_CAPTURE : SND_PCM_STREAM_PLAYBACK,
                             SND_PCM_NONBLOCK);
    if (error < 0) return fail(device, error);
    snd_pcm_hw_params_alloca(&hw);
    snd_pcm_sw_params_alloca(&sw);
    if ((error = snd_pcm_hw_params_any(pcm, hw)) < 0) return fail("hw params", error);
    if ((error = snd_pcm_hw_params_set_access(pcm, hw, SND_PCM_ACCESS_MMAP_INTERLEAVED)) < 0)
        return fail("mmap access", error);
    format = 0;
    for (unsigned n = 0; n < 3 && !format; ++n)
        if (!snd_pcm_hw_params_set_format(pcm, hw, formats[n])) format = sizes[n];
    if (!format) return fail("no S16_LE, S24_3LE or S32_LE format", 0);
    if ((error = snd_pcm_hw_params_set_channels(pcm, hw, channels)) < 0) return fail("channels", error);
    if ((error = snd_pcm_hw_params_set_rate(pcm, hw, rate, 0)) < 0) return fail("rate", error);
    if ((error = snd_pcm_hw_params_set_buffer_size_near(pcm, hw, &size)) < 0) return fail("buffer size", error);
    chunk = size / 8;
    if ((error = snd_pcm_hw_params_set_period_size_near(pcm, hw, &chunk, NULL)) < 0)
        return fail("period size", error);
    if ((error = snd_pcm_hw_params(pcm, hw)) < 0) return fail("hw params", error);
    if ((error = snd_pcm_hw_params_get_buffer_size(hw, &buffer)) < 0) return fail("buffer size", error);
    if (buffer < wanted) {
        fprintf(stderr, "rpi-audio-hostbridge: %s gives a buffer of %lu frames and a JACK period of %u needs %lu; "
                "use a shorter JACK period\n", device, (unsigned long)buffer, period, (unsigned long)wanted);
        return 1;
    }
    frame_bytes = format * channels;

    if ((error = snd_pcm_sw_params_current(pcm, sw)) < 0) return fail("sw params", error);
    if ((error = snd_pcm_sw_params_get_boundary(sw, &boundary)) < 0) return fail("boundary", error);
    // Started by hand, never stopped by an xrun, and never woken: nobody waits on this device.
    if ((error = snd_pcm_sw_params_set_start_threshold(pcm, sw, boundary)) < 0 ||
        (error = snd_pcm_sw_params_set_stop_threshold(pcm, sw, boundary)) < 0 ||
        (error = snd_pcm_sw_params_set_avail_min(pcm, sw, buffer)) < 0)
        return fail("sw params", error);
    // What the host reads past our audio is silence, not the buffer's old contents.
    if (!capture && ((error = snd_pcm_sw_params_set_silence_threshold(pcm, sw, 0)) < 0 ||
                     (error = snd_pcm_sw_params_set_silence_size(pcm, sw, boundary)) < 0))
        return fail("silence", error);
    if ((error = snd_pcm_sw_params(pcm, sw)) < 0) return fail("sw params", error);
    if ((error = snd_pcm_prepare(pcm)) < 0) return fail("prepare", error);

    const snd_pcm_channel_area_t *areas;
    snd_pcm_uframes_t offset, frames = 1;
    snd_pcm_avail_update(pcm);
    if ((error = snd_pcm_mmap_begin(pcm, &areas, &offset, &frames)) < 0) return fail("mmap", error);
    for (unsigned c = 0; c < channels; ++c)
        if (areas[c].addr != areas[0].addr || areas[c].step != frame_bytes * 8 ||
            areas[c].first != areas[0].first + c * format * 8)
            return fail("the device's buffer is not interleaved", 0);
    return 0;
}

static int number(const char *text, long low, long high, long *value) {
    char *end;
    *value = strtol(text, &end, 10);
    return *text && !*end && *value >= low && *value <= high;
}

int main(int argc, char **argv) {
    const char *name = NULL, *device = NULL, *direction = NULL;
    long value, margin_us = 1500, quality = 32;
    for (int n = 1; n < argc; n += 2) {
        const char *key = argv[n], *text = n + 1 < argc ? argv[n + 1] : NULL;
        if (!text) return 2;
        if (!strcmp(key, "--client")) name = text;
        else if (!strcmp(key, "--device")) device = text;
        else if (!strcmp(key, "--direction")) direction = text;
        else if (!strcmp(key, "--rate") && number(text, 8000, 192000, &value)) rate = (unsigned)value;
        else if (!strcmp(key, "--channels") && number(text, 1, HB_MAX_CHANNELS, &value)) channels = (unsigned)value;
        else if (!strcmp(key, "--margin-us") && number(text, 250, 20000, &value)) margin_us = value;
        else if (!strcmp(key, "--quality") && number(text, HB_MIN_QUALITY, HB_MAX_QUALITY, &value)) quality = value;
        else return 2;
    }
    if (!name || !device || !direction || !rate || !channels) return 2;
    if (!strcmp(direction, "capture")) capture = 1;
    else if (strcmp(direction, "playback")) return 2;

    jack_status_t status;
    const char *server = getenv("JACK_DEFAULT_SERVER");
    client = jack_client_open(name, JackNoStartServer | JackUseExactName | (server ? JackServerName : 0), &status,
                              server);
    if (!client) {
        fprintf(stderr, "rpi-audio-hostbridge: no JACK server, or the name %s is taken\n", name);
        return 1;
    }
    jack_rate = jack_get_sample_rate(client);
    period = jack_get_buffer_size(client);

    // One JACK period in gadget frames, with room for the loop's 1 % and rounding.
    const unsigned per_cycle = (unsigned)ceil((double)period * rate / jack_rate * (1 + HB_LOOP_LIMIT)) + 2;
    margin = (unsigned)lrint(margin_us * 1e-6 * rate);
    tolerance = margin > per_cycle / 2 ? margin : per_cycle / 2;
    if (open_device(device, 2 * (per_cycle + margin + tolerance))) {
        jack_client_close(client);
        return 1;
    }
    nominal_step = capture ? (double)rate / jack_rate : (double)jack_rate / rate;
    step = nominal_step;
    scratch_frames = capture ? period : per_cycle + 2;
    scratch = calloc((size_t)scratch_frames * channels, sizeof(float));
    if (!scratch || hb_resampler_init(&resampler, channels, (unsigned)quality, nominal_step,
                                      capture ? per_cycle + 2 : period)) {
        fprintf(stderr, "rpi-audio-hostbridge: out of memory\n");
        jack_client_close(client);
        return 1;
    }
    hb_loop_init(&loop);

    // What this bridge adds, for JACK's latency reports: the margin and the filter, in JACK frames.
    const double added = capture ? (margin + quality) * (double)jack_rate / rate
                                 : margin * (double)jack_rate / rate + quality;
    jack_latency_range_t range = {.min = (jack_nframes_t)lrint(added), .max = (jack_nframes_t)lrint(added)};
    for (unsigned c = 0; c < channels; ++c) {
        char port[32];
        snprintf(port, sizeof port, capture ? "capture_%u" : "playback_%u", c + 1);
        ports[c] = jack_port_register(client, port, JACK_DEFAULT_AUDIO_TYPE,
                                      (capture ? JackPortIsOutput : JackPortIsInput) | JackPortIsPhysical |
                                      JackPortIsTerminal, 0);
        if (!ports[c]) {
            fprintf(stderr, "rpi-audio-hostbridge: cannot register port %s\n", port);
            jack_client_close(client);
            return 1;
        }
        jack_port_set_latency_range(ports[c], capture ? JackCaptureLatency : JackPlaybackLatency, &range);
    }
    jack_on_shutdown(client, on_shutdown, NULL);
    jack_set_buffer_size_callback(client, on_change, &period);
    jack_set_sample_rate_callback(client, on_change, &jack_rate);
    jack_set_process_callback(client, capture ? process_capture : process_playback, NULL);
    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);
    mlockall(MCL_CURRENT | MCL_FUTURE);   // best effort: without the privilege it stays unlocked

    int error = snd_pcm_start(pcm);
    if (error < 0) {
        fail("start", error);
        jack_client_close(client);
        return 1;
    }
    if (jack_activate(client)) {
        fprintf(stderr, "rpi-audio-hostbridge: cannot activate the JACK client\n");
        jack_client_close(client);
        return 1;
    }

    setvbuf(stdout, NULL, _IOLBF, 0);
    static const char *const formats[] = {[HB_S16] = "S16_LE", [HB_S24_3] = "S24_3LE", [HB_S32] = "S32_LE"};
    int exit_code = 0, last_state = -1;
    unsigned last_resyncs = 0, ticks = 10;
    while (!stopping && atomic_load(&server_alive)) {
        const int problem = atomic_load(&failed);
        if (problem) {
            fprintf(stderr, "rpi-audio-hostbridge: %s\n", problem < 0 ? "JACK's period or rate changed"
                    : snd_strerror(-problem));
            exit_code = 1;
            break;
        }
        const int now_state = atomic_load(&state);
        const unsigned now_resyncs = atomic_load(&resyncs);
        if (++ticks >= 10 || now_state != last_state || now_resyncs != last_resyncs) {
            const unsigned count = atomic_exchange(&cycles, 0);
            const long sum = atomic_exchange(&fill_sum, 0);
            const int low = atomic_exchange(&fill_min, INT32_MAX), high = atomic_exchange(&fill_max, INT32_MIN);
            printf("{\"event\":\"status\",\"direction\":\"%s\",\"state\":\"%s\",\"resyncs\":%u,\"errors\":%u,"
                   "\"ppm\":%.1f,\"margin\":%u,\"fill_min\":%d,\"fill_avg\":%.1f,\"fill_max\":%d,"
                   "\"late_max_us\":%d,\"quality\":%ld,\"format\":\"%s\",\"rate\":%u,\"jack_rate\":%u,"
                   "\"period\":%u,\"buffer\":%lu}\n",
                   capture ? "capture" : "playback", now_state ? "running" : "waiting", now_resyncs,
                   atomic_load(&alsa_errors), atomic_load(&ppm10) / 10.0, margin, count ? low : 0,
                   count ? (double)sum / count : 0.0, count ? high : 0, atomic_exchange(&late_max, 0),
                   quality, formats[format], rate, jack_rate, period, (unsigned long)buffer);
            ticks = 0;
            last_state = now_state;
            last_resyncs = now_resyncs;
        }
        usleep(100000);
    }
    jack_deactivate(client);
    jack_client_close(client);
    snd_pcm_close(pcm);
    return exit_code;
}
