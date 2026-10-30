/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * Elastic buffer with a drift-correcting resampler: frames go in at one clock
 * and come out at another (the gadget's USB clock and the Force's internal
 * codec, ADA2, which runs ~31.7 ppm slow). The read ratio is steered so the
 * fill stays at its target. No ALSA in here, so it can be tested on any host.
 */
#ifndef MIO_CORE_H
#define MIO_CORE_H

#include <stddef.h>

#define MIO_TAPS 16      /* windowed-sinc length; latency is MIO_TAPS / 2 frames */
#define MIO_PHASES 64    /* kernel table resolution, linearly interpolated */

struct mio_elastic {
	float *ring;            /* interleaved frames */
	size_t cap, ch;         /* capacity in frames (a power of two), channels */
	size_t rd, wr;          /* monotonic frame counters; slot = counter & (cap - 1) */
	double frac;            /* fractional read position, [0, 1) */
	double ratio;           /* input frames consumed per output frame */
	double target;          /* wanted fill, in frames, counting the device's queue (see steer) */
	double fill_avg;        /* smoothed fill */
	double integ;           /* integral term of the steering loop */
	unsigned long underflows, overflows;
};

/* Builds the resampler kernel. Call once before any mio_elastic_pull. */
void mio_kernel_init(void);

int mio_elastic_init(struct mio_elastic *e, size_t ch, size_t cap, double target);
void mio_elastic_free(struct mio_elastic *e);
/* Empties the buffer and refills it with `prefill` frames of silence. */
void mio_elastic_reset(struct mio_elastic *e, size_t prefill);
size_t mio_elastic_fill(const struct mio_elastic *e);
/* Stores up to `frames` frames; what does not fit is dropped and counted. */
size_t mio_elastic_push(struct mio_elastic *e, const float *src, size_t frames);
/* Produces `frames` resampled frames; silence (and a count) when it runs dry. */
void mio_elastic_pull(struct mio_elastic *e, float *dst, size_t frames);
/* Updates the ratio from the fill plus `device` frames held on the device side
 * (queued for playback, or captured but not read yet). The device's pointer
 * moves smoothly, so the sum is a much less jumpy measure than the ring alone.
 * Call once after each round of push and pull. */
void mio_elastic_steer(struct mio_elastic *e, double device);

enum mio_fmt { MIO_S16, MIO_S32 };

/* One sample of an interleaved buffer, as float in [-1, 1). */
float mio_get(const void *buf, enum mio_fmt fmt, size_t index);
/* Writes one sample, clipping to the format's range. */
void mio_put(void *buf, enum mio_fmt fmt, size_t index, float v);

#endif
