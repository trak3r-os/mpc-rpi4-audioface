/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "mio_core.h"

#include <math.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define HALF (MIO_TAPS / 2)
#define CUTOFF 0.45             /* fraction of the sample rate: passband to ~19.8 kHz at 44.1 kHz */
#define MAX_PPM 1000e-6         /* the steering never moves the ratio further than this */

/* Steering loop. The fill is noisy (frames arrive in periods of 64-192), so it
 * is smoothed first. Per round (~344/s), with N = 128 frames, the loop is
 * f'' = -N (KP f' + KI f): natural frequency sqrt(N KI), damping N KP / (2 sqrt(N KI)).
 * The defaults give ~0.6 damping and settle a fixed drift in under a minute. */
#ifndef ALPHA
#define ALPHA (1.0 / 256)
#endif
#ifndef KP
#define KP 4e-6                 /* per frame of error */
#endif
#ifndef KI
#define KI 1.5e-9               /* per frame of error, per round */
#endif

static float kernel[MIO_PHASES + 1][MIO_TAPS];

void mio_kernel_init(void)
{
	for (int p = 0; p <= MIO_PHASES; p++) {
		double d = (double)p / MIO_PHASES, sum = 0;
		for (int k = 0; k < MIO_TAPS; k++) {
			double t = k - (HALF - 1) - d;          /* distance from the output instant */
			double x = 2 * CUTOFF * t;
			double sinc = fabs(x) < 1e-12 ? 1 : sin(M_PI * x) / (M_PI * x);
			double u = (t + HALF) / MIO_TAPS;      /* Blackman-Harris window over the taps */
			double w = u <= 0 || u >= 1 ? 0 :
				0.35875 - 0.48829 * cos(2 * M_PI * u) + 0.14128 * cos(4 * M_PI * u)
				- 0.01168 * cos(6 * M_PI * u);
			kernel[p][k] = (float)(sinc * w);
			sum += kernel[p][k];
		}
		for (int k = 0; k < MIO_TAPS; k++)
			kernel[p][k] = (float)(kernel[p][k] / sum);  /* unity gain at DC */
	}
}

int mio_elastic_init(struct mio_elastic *e, size_t ch, size_t cap, double target)
{
	size_t c = 1;
	while (c < cap)
		c <<= 1;
	memset(e, 0, sizeof(*e));
	e->ring = calloc(c * ch, sizeof(float));
	if (!e->ring)
		return -1;
	e->cap = c;
	e->ch = ch;
	e->target = target;
	mio_elastic_reset(e, 0);
	return 0;
}

void mio_elastic_free(struct mio_elastic *e)
{
	free(e->ring);
	e->ring = NULL;
}

void mio_elastic_reset(struct mio_elastic *e, size_t prefill)
{
	memset(e->ring, 0, e->cap * e->ch * sizeof(float));
	e->rd = 0;
	e->wr = prefill < e->cap ? prefill : e->cap;
	e->frac = 0;
	e->fill_avg = e->target;
	/* The ratio and its integral survive a reset: the drift between the clocks has not changed. */
}

size_t mio_elastic_fill(const struct mio_elastic *e)
{
	return e->wr - e->rd;
}

size_t mio_elastic_push(struct mio_elastic *e, const float *src, size_t frames)
{
	size_t room = e->cap - mio_elastic_fill(e), n = frames < room ? frames : room;
	for (size_t i = 0; i < n; i++) {
		float *slot = e->ring + ((e->wr + i) & (e->cap - 1)) * e->ch;
		memcpy(slot, src + i * e->ch, e->ch * sizeof(float));
	}
	e->wr += n;
	if (n < frames)
		e->overflows++;
	return n;
}

void mio_elastic_pull(struct mio_elastic *e, float *dst, size_t frames)
{
	const size_t mask = e->cap - 1;
	int dry = 0;
	for (size_t n = 0; n < frames; n++) {
		float *out = dst + n * e->ch;
		if (mio_elastic_fill(e) < MIO_TAPS + 1) {
			memset(out, 0, e->ch * sizeof(float));
			dry = 1;
			continue;
		}
		double phase = e->frac * MIO_PHASES;
		int i = (int)phase;
		float t = (float)(phase - i);
		float coef[MIO_TAPS];
		for (int k = 0; k < MIO_TAPS; k++)
			coef[k] = kernel[i][k] + t * (kernel[i + 1][k] - kernel[i][k]);
		for (size_t c = 0; c < e->ch; c++) {
			float acc = 0;
			for (int k = 0; k < MIO_TAPS; k++)
				acc += coef[k] * e->ring[((e->rd + k) & mask) * e->ch + c];
			out[c] = acc;
		}
		e->frac += e->ratio;
		double adv = floor(e->frac);
		e->frac -= adv;
		e->rd += (size_t)adv;
	}
	if (dry)
		e->underflows++;
}

void mio_elastic_steer(struct mio_elastic *e, double device)
{
	double fill = (double)mio_elastic_fill(e) + device;
	double err = (e->fill_avg += ALPHA * (fill - e->fill_avg)) - e->target;
	e->integ += KI * err;
	if (e->integ > MAX_PPM)
		e->integ = MAX_PPM;
	if (e->integ < -MAX_PPM)
		e->integ = -MAX_PPM;
	double r = 1 + KP * err + e->integ;
	e->ratio = r > 1 + MAX_PPM ? 1 + MAX_PPM : r < 1 - MAX_PPM ? 1 - MAX_PPM : r;
}

float mio_get(const void *buf, enum mio_fmt fmt, size_t index)
{
	if (fmt == MIO_S16)
		return ((const int16_t *)buf)[index] * (1.0f / 32768);
	return (float)(((const int32_t *)buf)[index] * (1.0 / 2147483648.0));
}

void mio_put(void *buf, enum mio_fmt fmt, size_t index, float v)
{
	if (v > 1)
		v = 1;
	if (v < -1)
		v = -1;
	if (fmt == MIO_S16) {
		long s = lrintf(v * 32768);
		((int16_t *)buf)[index] = (int16_t)(s > 32767 ? 32767 : s);
	} else {
		double s = (double)v * 2147483648.0;
		((int32_t *)buf)[index] = s >= 2147483647.0 ? INT32_MAX : (int32_t)s;
	}
}
