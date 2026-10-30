/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * Host test of mio_core, simulating both directions of the add-on as they run
 * on the Force: MPC acts every 128 frames of the gadget clock (with scheduling
 * jitter), the internal codec runs continuously on its own clock 31.7 ppm slow
 * (measured), and its pointer moves in steps of 64 frames. Checks that the
 * steering settles, that nothing runs dry or over, and that a sine comes
 * through clean. Exit status 0 on success.
 */
#include "mio_core.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>

#define RATE 44100.0
#define DRIFT (-31.7e-6)        /* codec clock relative to the gadget */
#define SECONDS 600
#define SETTLE 120              /* seconds before the checks start */
#define TONE 997.0
#define PERIOD 128              /* MPC's period on the gadget */
#define GRAIN 64                /* the codec's pointer granularity */
#define QUEUE 256               /* playback: frames kept queued in the codec */
#define RING 256                /* frames kept in the ring */
#define RECORD (10 * 44100)     /* output kept for the quality check */

static int failures;

static void check(int ok, const char *what)
{
	printf("%s %s\n", ok ? "ok  " : "FAIL", what);
	failures += !ok;
}

struct run {
	double ratio_sum, ratio_sq, worst_dev;
	long ratio_n;
	unsigned long under, over, codec_xruns;
	float *rec;
	size_t rec_n;
};

/* Noise and distortion of a sine, in dB below it: Blackman-Harris windowed
 * spectrum of the last 16384 samples, with everything within +-50 Hz of the tone
 * counted as the tone. The steering moves the ratio by a few ppm, an inaudible
 * flutter (~0.002 %) that only spreads the tone by a few hertz. */
#define NFFT 16384
static double residual_db(const float *y, size_t n, double cycles)
{
	static double re[NFFT], im[NFFT];
	if (n < NFFT)
		return 0;
	for (int i = 0; i < NFFT; i++) {
		double u = (double)i / (NFFT - 1);
		double w = 0.35875 - 0.48829 * cos(2 * M_PI * u) + 0.14128 * cos(4 * M_PI * u) - 0.01168 * cos(6 * M_PI * u);
		re[i] = y[n - NFFT + i] * w;
		im[i] = 0;
	}
	for (int i = 1, j = 0; i < NFFT; i++) {          /* iterative radix-2 FFT */
		int bit = NFFT >> 1;
		for (; j & bit; bit >>= 1)
			j ^= bit;
		j ^= bit;
		if (i < j) {
			double t = re[i]; re[i] = re[j]; re[j] = t;
			t = im[i]; im[i] = im[j]; im[j] = t;
		}
	}
	for (int len = 2; len <= NFFT; len <<= 1) {
		double ang = -2 * M_PI / len;
		for (int i = 0; i < NFFT; i += len)
			for (int k = 0; k < len / 2; k++) {
				double wr = cos(ang * k), wi = sin(ang * k);
				double xr = re[i + k + len / 2] * wr - im[i + k + len / 2] * wi;
				double xi = re[i + k + len / 2] * wi + im[i + k + len / 2] * wr;
				re[i + k + len / 2] = re[i + k] - xr; im[i + k + len / 2] = im[i + k] - xi;
				re[i + k] += xr; im[i + k] += xi;
			}
	}
	double tone = 0, rest = 0, centre = cycles * NFFT, half = 50.0 / RATE * NFFT;
	for (int k = 1; k < NFFT / 2; k++) {
		double pw = re[k] * re[k] + im[k] * im[k];
		if (fabs(k - centre) <= half)
			tone += pw;
		else
			rest += pw;
	}
	return 10 * log10(fmax(rest, 1e-30) / tone);
}

static double jitter(int on)
{
	return on ? (rand() / (double)RAND_MAX - 0.5) * 1e-3 : 0;  /* +-0.5 ms */
}

static void track(struct run *r, const struct mio_elastic *e, double t, unsigned long under, unsigned long over)
{
	if (t < SETTLE)
		return;
	r->under += e->underflows - under;
	r->over += e->overflows - over;
	if (fabs(e->fill_avg - e->target) > r->worst_dev)
		r->worst_dev = fabs(e->fill_avg - e->target);
	r->ratio_sum += e->ratio;
	r->ratio_sq += e->ratio * e->ratio;
	r->ratio_n++;
}

static void keep(struct run *r, const float *out, size_t n, double t)
{
	if (t < SECONDS - 11)
		return;
	for (size_t i = 0; i < n && r->rec_n < RECORD; i++)
		r->rec[r->rec_n++] = out[i];
}

/* MPC -> codec: MPC writes a period at the gadget clock; the add-on tops the
 * codec's queue up to QUEUE, steering on ring + queue. */
static void playback(int jit, struct run *r)
{
	const double codec_rate = RATE * (1 + DRIFT);
	struct mio_elastic e;
	float in[PERIOD], out[2 * QUEUE];
	long written = QUEUE;   /* the codec starts with QUEUE frames of silence */
	mio_elastic_init(&e, 1, 4096, RING + QUEUE);
	mio_elastic_reset(&e, RING);
	for (long k = 0;; k++) {
		double t = k * PERIOD / RATE + jitter(jit);
		if (t > SECONDS)
			break;
		unsigned long under = e.underflows, over = e.overflows;
		for (int i = 0; i < PERIOD; i++)
			in[i] = (float)(0.5 * sin(2 * M_PI * TONE * (k * PERIOD + i) / RATE));
		mio_elastic_push(&e, in, PERIOD);
		long consumed = (long)(codec_rate * t / GRAIN) * GRAIN;
		long delay = written - consumed;
		if (delay < 0) {
			if (t >= SETTLE)
				r->codec_xruns++;
			written = consumed;
			delay = 0;
		}
		long want = QUEUE - delay;
		if (want > 0) {
			mio_elastic_pull(&e, out, (size_t)want);
			written += want;
			keep(r, out, (size_t)want, t);
		}
		mio_elastic_steer(&e, (double)(written - consumed));
		track(r, &e, t, under, over);
	}
	mio_elastic_free(&e);
}

/* Codec -> MPC: on each MPC read, the add-on takes everything the codec has
 * captured, then produces one period for MPC. `jump` makes the gadget lose
 * 164 frames at 300 s, as seen once on the Force. */
static void capture(int jit, int jump, struct run *r)
{
	const double codec_rate = RATE * (1 + DRIFT);
	struct mio_elastic e;
	float in[4096], out[PERIOD];
	long got = 0;
	double shift = 0;
	mio_elastic_init(&e, 1, 4096, RING);
	mio_elastic_reset(&e, RING);
	for (long k = 0;; k++) {
		double t = k * PERIOD / RATE + shift + jitter(jit);
		if (t > SECONDS)
			break;
		if (jump && shift == 0 && t > 300)
			shift = 164 / RATE;
		unsigned long under = e.underflows, over = e.overflows;
		long avail = (long)(codec_rate * t / GRAIN) * GRAIN - got;
		for (long i = 0; i < avail; i++)
			in[i] = (float)(0.5 * sin(2 * M_PI * TONE * (got + i) / codec_rate));
		if (avail > 0)
			mio_elastic_push(&e, in, (size_t)avail);
		got += avail;
		mio_elastic_pull(&e, out, PERIOD);
		keep(r, out, PERIOD, t);
		mio_elastic_steer(&e, 0);
		/* the jump itself is not a fault: start counting again a minute after it */
		if (!jump || t < 300 || t > 360)
			track(r, &e, t, under, over);
	}
	mio_elastic_free(&e);
}

static void report(const char *name, struct run *r, double expect_ratio, double cycles, int steady)
{
	double mean = r->ratio_sum / r->ratio_n;
	double flutter = sqrt(fmax(r->ratio_sq / r->ratio_n - mean * mean, 0));
	double db = residual_db(r->rec, r->rec_n, cycles);
	/* With perfectly regular periods (no jitter) MPC's phase beats against the codec's
	 * 64-frame steps every ~45 s; the loop follows that slow error. Real MPC timing
	 * jitters, which breaks the beat, so the steady cases get looser bounds. */
	double ratio_tol = steady ? 1e-6 : 0.5e-6, dev_tol = steady ? 64 : 32;
	printf("     %s: ratio %+.3f ppm (expected %+.3f), flutter %.2f ppm, worst smoothed-fill deviation %.1f "
	       "frames, noise+distortion %.1f dB\n", name, (mean - 1) * 1e6, (expect_ratio - 1) * 1e6, flutter * 1e6,
	       r->worst_dev, db);
	check(fabs(mean - expect_ratio) < ratio_tol, "  ratio settles to the clock difference");
	check(r->under == 0 && r->over == 0 && r->codec_xruns == 0, "  no underflow, overflow or codec xrun once settled");
	check(r->worst_dev < dev_tol, "  smoothed fill stays near its target");
	/* Flutter is audible from roughly 0.1 % (1000 ppm); a faster loop that recovers from
	 * jumps quickly is worth a few tens of ppm. */
	check(flutter < 100e-6, "  ratio flutter below 100 ppm (0.01 %)");
	check(db < -80, "  a sine comes through at least 80 dB clean");
}

static void directions(void)
{
	const double codec_rate = RATE * (1 + DRIFT);
	struct {
		const char *name;
		int playback, jitter, jump;
	} cases[] = {
		{"playback, steady", 1, 0, 0},
		{"playback, MPC jitter +-0.5 ms", 1, 1, 0},
		{"capture, steady", 0, 0, 0},
		{"capture, MPC jitter +-0.5 ms", 0, 1, 0},
		{"capture, 164-frame gadget jump at 300 s", 0, 1, 1},
	};
	for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); i++) {
		struct run r = {0};
		r.rec = malloc(RECORD * sizeof(float));
		srand(1);
		if (cases[i].playback) {
			playback(cases[i].jitter, &r);
			report(cases[i].name, &r, RATE / codec_rate, TONE / codec_rate, !cases[i].jitter);
		} else {
			capture(cases[i].jitter, cases[i].jump, &r);
			report(cases[i].name, &r, codec_rate / RATE, TONE / RATE, !cases[i].jitter);
		}
		free(r.rec);
	}
}

static void unity_dc(void)
{
	/* A constant pulled through at a fractional ratio must come out unchanged. */
	struct mio_elastic e;
	float in[512], out[256], worst = 0;
	mio_elastic_init(&e, 1, 1024, 0);
	for (int i = 0; i < 512; i++)
		in[i] = 0.5f;
	mio_elastic_push(&e, in, 512);
	e.ratio = 1.37;
	mio_elastic_pull(&e, out, 256);
	for (int i = 0; i < 256; i++)
		worst = fmaxf(worst, fabsf(out[i] - 0.5f));
	check(worst < 1e-5f, "DC passes at unity gain at any phase");
	mio_elastic_free(&e);
}

static void formats(void)
{
	short s16[2] = {0};
	int s32[2] = {0};
	mio_put(s16, MIO_S16, 0, 1.5f);
	mio_put(s16, MIO_S16, 1, -0.25f);
	mio_put(s32, MIO_S32, 0, 1.5f);
	mio_put(s32, MIO_S32, 1, -0.25f);
	check(s16[0] == 32767 && s16[1] == -8192, "S16 put clips and scales");
	check(s32[0] == 2147483647 && s32[1] == -536870912, "S32 put clips and scales");
	check(fabsf(mio_get(s16, MIO_S16, 1) + 0.25f) < 1e-6f && fabsf(mio_get(s32, MIO_S32, 1) + 0.25f) < 1e-6f,
	      "get inverts put");
}

int main(void)
{
	mio_kernel_init();
	unity_dc();
	formats();
	directions();
	printf("%s\n", failures ? "FAIL" : "OK");
	return failures != 0;
}
