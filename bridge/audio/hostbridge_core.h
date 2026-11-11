// SPDX-License-Identifier: GPL-3.0-or-later
// The hardware-free half of rpi-audio-hostbridge (hostbridge.c): a variable-ratio resampler,
// the loop that steers it from a buffer's fill, and the sample conversions. No ALSA, no JACK
// and no allocation after setup, so it runs in a realtime callback and in a plain test.
#ifndef RPI_AUDIO_HOSTBRIDGE_CORE_H
#define RPI_AUDIO_HOSTBRIDGE_CORE_H

#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define HB_PHASES 256        // filter phases; coefficients are interpolated between two of them
#define HB_MIN_QUALITY 8
#define HB_MAX_QUALITY 96
#define HB_MAX_CHANNELS 64
#define HB_PI 3.14159265358979323846

// --- resampler ---------------------------------------------------------------------------
//
// A windowed-sinc interpolator of 2 * half taps. Outputs are taken at positions `step` input
// frames apart; step changes a little on every call, which is how the two clocks are matched.
// An output needs `half` input frames after its position: that is the filter's delay.

typedef struct {
    unsigned channels, half, taps;
    float *table;            // (HB_PHASES + 1) rows of `taps` coefficients
    float *buf;              // interleaved input: the history, then what the caller appended
    unsigned capacity, have; // frames
    double pos;              // position of the next output in buf, in frames
} hb_resampler;

static inline double hb_bessel_i0(double x) {
    double sum = 1, term = 1;
    for (int k = 1; k < 64; ++k) {
        term *= (x / (2 * k)) * (x / (2 * k));
        sum += term;
        if (term < sum * 1e-17) break;
    }
    return sum;
}

// Stopband attenuation in dB of a Kaiser design this long with a transition 0.085 of the input
// rate wide (20 to 24.1 kHz at 48 kHz), and the window's beta for it.
static inline double hb_attenuation(unsigned half) {
    double a = 7.95 + 14.36 * (2.0 * half) * 0.085;
    return a > 140 ? 140 : a;
}

static inline double hb_kaiser_beta(double a) {
    if (a > 50) return 0.1102 * (a - 8.7);
    if (a > 21) return 0.5842 * pow(a - 21, 0.4) + 0.07886 * (a - 21);
    return 0;
}

// nominal_step: input frames per output frame (input rate / output rate). max_in: the most
// input frames one hb_process call can need. Returns 0, or -1 when out of memory or arguments.
static inline int hb_resampler_init(hb_resampler *r, unsigned channels, unsigned half,
                                    double nominal_step, unsigned max_in) {
    memset(r, 0, sizeof *r);
    if (!channels || channels > HB_MAX_CHANNELS || half < HB_MIN_QUALITY || half > HB_MAX_QUALITY ||
        !(nominal_step > 0.1 && nominal_step < 10))
        return -1;
    r->channels = channels;
    r->half = half;
    r->taps = 2 * half;
    r->capacity = r->taps + max_in + 8;
    r->table = malloc(sizeof(float) * (HB_PHASES + 1) * r->taps);
    r->buf = calloc((size_t)r->capacity * channels, sizeof(float));
    if (!r->table || !r->buf) {
        free(r->table);
        free(r->buf);
        memset(r, 0, sizeof *r);
        return -1;
    }
    // Cutoff at the lower of the two Nyquist frequencies, as a fraction of the input rate.
    const double fc = nominal_step > 1 ? 0.5 / nominal_step : 0.5;
    const double beta = hb_kaiser_beta(hb_attenuation(half)), norm = hb_bessel_i0(beta);
    for (unsigned phase = 0; phase <= HB_PHASES; ++phase) {
        float *row = r->table + (size_t)phase * r->taps;
        double sum = 0;
        for (unsigned t = 0; t < r->taps; ++t) {
            const double x = (double)t - (half - 1) - (double)phase / HB_PHASES;
            const double w = 1 - (x / half) * (x / half);
            const double arg = 2 * HB_PI * fc * x;
            const double sinc = fabs(arg) < 1e-9 ? 1 : sin(arg) / arg;
            const double h = w > 0 ? 2 * fc * sinc * hb_bessel_i0(beta * sqrt(w)) / norm : 0;
            row[t] = (float)h;
            sum += h;
        }
        for (unsigned t = 0; t < r->taps; ++t) row[t] = (float)(row[t] / sum);   // unity gain at DC
    }
    r->have = r->taps - 1;   // silence as the first history
    r->pos = half - 1;
    return 0;
}

static inline void hb_resampler_free(hb_resampler *r) {
    free(r->table);
    free(r->buf);
    memset(r, 0, sizeof *r);
}

// Input frames still to append before `outputs` frames can be made at this step.
static inline unsigned hb_need(const hb_resampler *r, unsigned outputs, double step) {
    if (!outputs) return 0;
    const double last = r->pos + (outputs - 1) * step;
    const long need = (long)last + (long)r->half + 1 - (long)r->have;
    return need > 0 ? (unsigned)need : 0;
}

// Output frames the buffered input is enough for at this step.
static inline unsigned hb_ready(const hb_resampler *r, double step) {
    const double room = (double)r->have - r->half - r->pos;   // an output at p needs p + half < have
    if (room <= 0) return 0;
    const double n = ceil(room / step);
    return n > 0 ? (unsigned)n : 0;
}

// Where the caller writes `frames` new interleaved frames, or NULL when they do not fit.
static inline float *hb_append(hb_resampler *r, unsigned frames) {
    if (r->have + frames > r->capacity) return NULL;
    float *at = r->buf + (size_t)r->have * r->channels;
    r->have += frames;
    return at;
}

// Makes `outputs` interleaved frames in dst (the caller made sure the input is there, with
// hb_need or hb_ready) and drops the input that is no longer needed.
static inline void hb_process(hb_resampler *r, unsigned outputs, double step, float *dst) {
    const unsigned channels = r->channels, taps = r->taps;
    float coeff[2 * HB_MAX_QUALITY];
    for (unsigned n = 0; n < outputs; ++n) {
        const double p = r->pos + n * step;
        const unsigned ip = (unsigned)p;
        const double phase = (p - ip) * HB_PHASES;
        const unsigned row = (unsigned)phase;
        const float mix = (float)(phase - row);
        const float *c0 = r->table + (size_t)row * taps, *c1 = c0 + taps;
        for (unsigned t = 0; t < taps; ++t) coeff[t] = c0[t] + mix * (c1[t] - c0[t]);
        const float *src = r->buf + (size_t)(ip - (r->half - 1)) * channels;
        float sum[HB_MAX_CHANNELS] = {0};   // local, so the compiler can vectorise across channels
        for (unsigned t = 0; t < taps; ++t) {
            const float k = coeff[t];
            const float *frame = src + (size_t)t * channels;
            for (unsigned c = 0; c < channels; ++c) sum[c] += k * frame[c];
        }
        memcpy(dst + (size_t)n * channels, sum, sizeof(float) * channels);
    }
    const double next = r->pos + outputs * step;
    const unsigned drop = (unsigned)next - (r->half - 1);
    if (drop >= r->have) {   // cannot happen after hb_need / hb_ready; keep the state sane anyway
        memset(r->buf, 0, sizeof(float) * (r->taps - 1) * channels);
        r->have = r->taps - 1;
        r->pos = r->half - 1;
        return;
    }
    memmove(r->buf, r->buf + (size_t)drop * channels, sizeof(float) * (r->have - drop) * channels);
    r->have -= drop;
    r->pos = next - drop;
}

// --- control loop ------------------------------------------------------------------------
//
// A critically damped PI loop on the fill error of the buffer between the two clocks. The
// error is smoothed first: the fill moves a USB packet at a time. Its output multiplies the
// resampler's step: above 1 consumes the faster side quicker, which is what a positive error
// (too much buffered) asks for, in both directions.

typedef struct {
    double w, tau;           // loop bandwidth in rad/s; smoothing time constant in s
    double smooth, integral; // smoothed error in seconds; the learnt clock offset
    double correction;
} hb_loop;

#define HB_LOOP_HZ 0.1
#define HB_LOOP_SMOOTH_S 0.1
#define HB_LOOP_LIMIT 0.01       // the step never moves more than 1 % from nominal

static inline void hb_loop_init(hb_loop *l) {
    memset(l, 0, sizeof *l);
    l->w = 2 * HB_PI * HB_LOOP_HZ;
    l->tau = HB_LOOP_SMOOTH_S;
    l->correction = 1;
}

// After a jump in the fill (a resync): forget the smoothed error, keep the clock offset.
static inline void hb_loop_resync(hb_loop *l) {
    l->smooth = 0;
    l->correction = 1 + l->integral;
}

// error_s: (fill - target) in seconds; dt: seconds since the last update. Returns the new
// multiplier for the nominal step.
static inline double hb_loop_update(hb_loop *l, double error_s, double dt) {
    l->smooth += (1 - exp(-dt / l->tau)) * (error_s - l->smooth);
    l->integral += l->w * l->w * l->smooth * dt;
    if (l->integral > HB_LOOP_LIMIT / 2) l->integral = HB_LOOP_LIMIT / 2;
    if (l->integral < -HB_LOOP_LIMIT / 2) l->integral = -HB_LOOP_LIMIT / 2;
    double c = 2 * l->w * l->smooth + l->integral;
    if (c > HB_LOOP_LIMIT) c = HB_LOOP_LIMIT;
    if (c < -HB_LOOP_LIMIT) c = -HB_LOOP_LIMIT;
    l->correction = 1 + c;
    return l->correction;
}

// --- sample formats ----------------------------------------------------------------------

enum { HB_S16 = 2, HB_S24_3 = 3, HB_S32 = 4 };   // bytes per sample, little-endian

static inline void hb_to_float(const void *src, float *dst, size_t samples, int format) {
    if (format == HB_S16) {
        const int16_t *s = src;
        for (size_t n = 0; n < samples; ++n) dst[n] = s[n] * (1.f / 32768.f);
    } else if (format == HB_S32) {
        const int32_t *s = src;
        for (size_t n = 0; n < samples; ++n) dst[n] = (float)(s[n] * (1.0 / 2147483648.0));
    } else {
        const uint8_t *s = src;
        for (size_t n = 0; n < samples; ++n, s += 3) {
            const int32_t v = (int32_t)((uint32_t)s[0] << 8 | (uint32_t)s[1] << 16 | (uint32_t)s[2] << 24);
            dst[n] = (float)(v * (1.0 / 2147483648.0));
        }
    }
}

static inline float hb_clip(float x) {
    if (!(x == x)) return 0;   // NaN
    return x > 1.f ? 1.f : x < -1.f ? -1.f : x;
}

static inline void hb_from_float(const float *src, void *dst, size_t samples, int format) {
    if (format == HB_S16) {
        int16_t *d = dst;
        for (size_t n = 0; n < samples; ++n) {
            const long v = lrintf(hb_clip(src[n]) * 32768.f);
            d[n] = (int16_t)(v > 32767 ? 32767 : v);
        }
    } else if (format == HB_S32) {
        int32_t *d = dst;
        for (size_t n = 0; n < samples; ++n) {
            const double v = (double)hb_clip(src[n]) * 2147483648.0;
            d[n] = v >= 2147483647.0 ? INT32_MAX : (int32_t)lrint(v);
        }
    } else {
        uint8_t *d = dst;
        for (size_t n = 0; n < samples; ++n, d += 3) {
            const long v = lrintf(hb_clip(src[n]) * 8388608.f);
            const uint32_t u = (uint32_t)(v > 8388607 ? 8388607 : v);
            d[0] = (uint8_t)u;
            d[1] = (uint8_t)(u >> 8);
            d[2] = (uint8_t)(u >> 16);
        }
    }
}

#endif
