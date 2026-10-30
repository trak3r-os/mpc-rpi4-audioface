/* SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * MockbaMod add-on for the Akai Force, loaded into MPC with LD_PRELOAD.
 *
 * MPC uses a single audio device. While that device is the rpi-audio gadget,
 * this add-on copies some of MPC's output channels to the Force's own codec
 * (ADA2: main outs and headphones) and replaces some of MPC's input channels
 * with the codec's inputs, so the Force keeps its analogue I/O next to the
 * Pi's channels. ADA2 runs ~31.7 ppm slower than the gadget; mio_core
 * resamples across the two clocks.
 *
 * It never blocks MPC's audio thread: the codec is opened non-blocking and
 * serviced inside MPC's own readi/writei calls on the gadget. When anything
 * fails, that direction passes MPC's audio through untouched.
 *
 * Settings: mpc_internal_io.conf next to this .so ("key = value", # comments),
 * each overridable by an MIO_<KEY> environment variable. See
 * docs/hosts/akai-force-internal-io.md.
 */
#define _GNU_SOURCE
#include <alsa/asoundlib.h>
#include <ctype.h>
#include <dlfcn.h>
#include <errno.h>
#include <math.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "mio_core.h"

#define MAXMAP 8
#define EXPORT __attribute__((visibility("default")))  /* built with -fvisibility=hidden */
#define LOG_EVERY 10000         /* rounds between status lines, ~30 s at 128 frames */

struct map {
	int gadget, codec;      /* 0-based channels */
};

static struct {
	char gadget_id[32];     /* ALSA card id of the gadget */
	char codec_pcm[64];     /* PCM name of the Force's own codec */
	struct map play[MAXMAP], cap[MAXMAP];
	int nplay, ncap;
	float gain;             /* linear, on what goes to the codec */
	unsigned period, buffer, queue, ring;
	int verbose, off;
} cfg;

static struct {
	int (*open)(snd_pcm_t **, const char *, snd_pcm_stream_t, int);
	int (*close)(snd_pcm_t *);
	int (*hw_params)(snd_pcm_t *, snd_pcm_hw_params_t *);
	int (*prepare)(snd_pcm_t *);
	int (*recover)(snd_pcm_t *, int, int);
	snd_pcm_sframes_t (*readi)(snd_pcm_t *, void *, snd_pcm_uframes_t);
	snd_pcm_sframes_t (*writei)(snd_pcm_t *, const void *, snd_pcm_uframes_t);
} real;

/* One direction: MPC's handle on the gadget and ours on the codec. */
struct dir {
	const char *name;
	snd_pcm_stream_t stream;
	snd_pcm_t *gadget;      /* NULL when MPC has no such stream open */
	int gch;                /* gadget channels */
	enum mio_fmt gfmt;
	unsigned rate;
	snd_pcm_t *codec;       /* NULL until opened, or after giving up */
	int cch;                /* codec channels */
	struct map *map;
	int nmap;
	struct mio_elastic el;
	float *tmp;             /* cch-channel float frames */
	int32_t *raw;           /* cch-channel S32_LE frames, the codec's format */
	size_t frames;          /* capacity of tmp and raw */
	int resync;
	unsigned long rounds, codec_xruns;
};

static struct dir play = {.name = "playback", .stream = SND_PCM_STREAM_PLAYBACK};
static struct dir cap = {.name = "capture", .stream = SND_PCM_STREAM_CAPTURE};
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_once_t once = PTHREAD_ONCE_INIT;

static void say(const char *fmt, ...)
{
	va_list ap;
	va_start(ap, fmt);
	fprintf(stderr, "[mpc_internal_io] ");
	vfprintf(stderr, fmt, ap);
	fputc('\n', stderr);
	va_end(ap);
}

static char *trim(char *s)
{
	while (isspace((unsigned char)*s))
		s++;
	char *e = s + strlen(s);
	while (e > s && isspace((unsigned char)e[-1]))
		*--e = 0;
	return s;
}

/* "g:c,g:c" with 1-based channels: gadget channel g pairs with codec channel c. */
static int parse_map(const char *text, struct map *m)
{
	int n = 0, g, c, used;
	while (n < MAXMAP && sscanf(text, " %d : %d%n", &g, &c, &used) == 2) {
		if (g >= 1 && c >= 1)
			m[n++] = (struct map){g - 1, c - 1};
		text += used;
		while (*text == ',' || isspace((unsigned char)*text))
			text++;
	}
	return n;
}

static void set(const char *key, const char *val)
{
	if (!strcmp(key, "gadget_id"))
		snprintf(cfg.gadget_id, sizeof(cfg.gadget_id), "%s", val);
	else if (!strcmp(key, "codec_pcm"))
		snprintf(cfg.codec_pcm, sizeof(cfg.codec_pcm), "%s", val);
	else if (!strcmp(key, "playback"))
		cfg.nplay = parse_map(val, cfg.play);
	else if (!strcmp(key, "capture"))
		cfg.ncap = parse_map(val, cfg.cap);
	else if (!strcmp(key, "gain_db"))
		cfg.gain = powf(10, (float)atof(val) / 20);
	else if (!strcmp(key, "period"))
		cfg.period = (unsigned)atoi(val);
	else if (!strcmp(key, "buffer"))
		cfg.buffer = (unsigned)atoi(val);
	else if (!strcmp(key, "queue"))
		cfg.queue = (unsigned)atoi(val);
	else if (!strcmp(key, "ring"))
		cfg.ring = (unsigned)atoi(val);
	else if (!strcmp(key, "verbose"))
		cfg.verbose = atoi(val);
	else if (!strcmp(key, "off"))
		cfg.off = atoi(val);
	else
		say("unknown setting '%s'", key);
}

static void load_config(void)
{
	static const char *keys[] = {"gadget_id", "codec_pcm", "playback", "capture", "gain_db", "period",
				     "buffer", "queue", "ring", "verbose", "off"};
	/* Defaults: MPC's main out (1/2) to the codec's outs 1/2 and 3/4; the codec's two
	 * inputs as MPC inputs 25/26; -12 dB on the way out, as the Force's volume knob
	 * does nothing while MPC is on an external device. */
	set("gadget_id", "rpiaudio");
	set("codec_pcm", "hw:CARD=ADA2");
	set("playback", "1:1,2:2,1:3,2:4");
	set("capture", "25:1,26:2");
	set("gain_db", "-12");
	set("period", "64");
	set("buffer", "1024");
	set("queue", "256");
	set("ring", "256");
	set("verbose", "1");
	set("off", "0");

	Dl_info info;
	char path[512], line[256];
	if (dladdr((void *)load_config, &info) && info.dli_fname) {
		snprintf(path, sizeof(path), "%s", info.dli_fname);
		char *slash = strrchr(path, '/');
		snprintf(slash ? slash + 1 : path, sizeof(path) - (slash ? (size_t)(slash + 1 - path) : 0),
			 "mpc_internal_io.conf");
		FILE *f = fopen(path, "r");
		if (f) {
			while (fgets(line, sizeof(line), f)) {
				char *hash = strchr(line, '#'), *eq;
				if (hash)
					*hash = 0;
				if ((eq = strchr(line, '='))) {
					*eq = 0;
					set(trim(line), trim(eq + 1));
				}
			}
			fclose(f);
		}
	}
	for (size_t i = 0; i < sizeof(keys) / sizeof(keys[0]); i++) {
		char env[32], *v;
		snprintf(env, sizeof(env), "MIO_%s", keys[i]);
		for (char *p = env; *p; p++)
			*p = (char)toupper((unsigned char)*p);
		if ((v = getenv(env)))
			set(keys[i], v);
	}
}

static void init(void)
{
	real.open = dlsym(RTLD_NEXT, "snd_pcm_open");
	real.close = dlsym(RTLD_NEXT, "snd_pcm_close");
	real.hw_params = dlsym(RTLD_NEXT, "snd_pcm_hw_params");
	real.prepare = dlsym(RTLD_NEXT, "snd_pcm_prepare");
	real.recover = dlsym(RTLD_NEXT, "snd_pcm_recover");
	real.readi = dlsym(RTLD_NEXT, "snd_pcm_readi");
	real.writei = dlsym(RTLD_NEXT, "snd_pcm_writei");
	load_config();
	mio_kernel_init();
	play.map = cfg.play;
	play.nmap = cfg.nplay;
	cap.map = cfg.cap;
	cap.nmap = cfg.ncap;
	say("loaded%s: gadget '%s', codec '%s', %d playback and %d capture pairs, gain %.1f dB",
	    cfg.off ? " but switched off" : "", cfg.gadget_id, cfg.codec_pcm, cfg.nplay, cfg.ncap,
	    20 * log10f(cfg.gain));
}

static struct dir *dir_of(snd_pcm_t *pcm)
{
	return pcm && pcm == play.gadget ? &play : pcm && pcm == cap.gadget ? &cap : NULL;
}

static int card_id(snd_pcm_t *pcm, char *id, size_t n)
{
	snd_pcm_info_t *info;
	snd_ctl_card_info_t *ci;
	snd_ctl_t *ctl;
	char hw[16];
	snd_pcm_info_alloca(&info);
	snd_ctl_card_info_alloca(&ci);
	if (snd_pcm_info(pcm, info) < 0 || snd_pcm_info_get_card(info) < 0)
		return -1;
	snprintf(hw, sizeof(hw), "hw:%d", snd_pcm_info_get_card(info));
	if (snd_ctl_open(&ctl, hw, 0) < 0)
		return -1;
	int err = snd_ctl_card_info(ctl, ci);
	if (!err)
		snprintf(id, n, "%s", snd_ctl_card_info_get_id(ci));
	snd_ctl_close(ctl);
	return err;
}

static void codec_close(struct dir *d)
{
	if (d->codec) {
		say("%s: closing the codec after %lu rounds, %lu codec xruns, %lu underflows, %lu overflows, "
		    "ratio %+.2f ppm", d->name, d->rounds, d->codec_xruns, d->el.underflows, d->el.overflows,
		    (d->el.ratio - 1) * 1e6);
		real.close(d->codec);
		d->codec = NULL;
	}
	mio_elastic_free(&d->el);
	free(d->tmp);
	free(d->raw);
	d->tmp = NULL;
	d->raw = NULL;
}

/* Opens the codec to match the gadget stream MPC has just configured. */
static int codec_open(struct dir *d, snd_pcm_uframes_t gadget_buffer)
{
	snd_pcm_t *h;
	snd_pcm_hw_params_t *hw;
	snd_pcm_sw_params_t *sw;
	snd_pcm_uframes_t period = cfg.period, buffer = cfg.buffer;
	int err, ch = 2;
	for (int i = 0; i < d->nmap; i++)
		if (d->map[i].codec + 1 > ch)
			ch = d->map[i].codec + 1;
	if ((err = real.open(&h, cfg.codec_pcm, d->stream, SND_PCM_NONBLOCK)) < 0) {
		say("%s: cannot open %s: %s", d->name, cfg.codec_pcm, snd_strerror(err));
		return err;
	}
	snd_pcm_hw_params_alloca(&hw);
	snd_pcm_sw_params_alloca(&sw);
	if ((err = snd_pcm_hw_params_any(h, hw)) < 0 ||
	    (err = snd_pcm_hw_params_set_access(h, hw, SND_PCM_ACCESS_RW_INTERLEAVED)) < 0 ||
	    (err = snd_pcm_hw_params_set_format(h, hw, SND_PCM_FORMAT_S32_LE)) < 0 ||
	    (err = snd_pcm_hw_params_set_channels(h, hw, (unsigned)ch)) < 0 ||
	    (err = snd_pcm_hw_params_set_rate(h, hw, d->rate, 0)) < 0 ||
	    (err = snd_pcm_hw_params_set_period_size_near(h, hw, &period, NULL)) < 0 ||
	    (err = snd_pcm_hw_params_set_buffer_size_near(h, hw, &buffer)) < 0 ||
	    (err = real.hw_params(h, hw)) < 0 ||
	    (err = snd_pcm_sw_params_current(h, sw)) < 0 ||
	    (err = snd_pcm_sw_params_set_start_threshold(h, sw, buffer * 2)) < 0 ||  /* started by hand */
	    (err = snd_pcm_sw_params_set_avail_min(h, sw, period)) < 0 ||
	    (err = snd_pcm_sw_params(h, sw)) < 0) {
		say("%s: cannot set up %s (%u ch, S32_LE, %u Hz): %s", d->name, cfg.codec_pcm, ch, d->rate,
		    snd_strerror(err));
		real.close(h);
		return err;
	}
	d->frames = gadget_buffer + buffer + 64;
	d->tmp = malloc(d->frames * (size_t)ch * sizeof(float));
	d->raw = malloc(d->frames * (size_t)ch * sizeof(int32_t));
	double target = cfg.ring + (d->stream == SND_PCM_STREAM_PLAYBACK ? cfg.queue : 0);
	if (!d->tmp || !d->raw || mio_elastic_init(&d->el, (size_t)ch, 4096, target) < 0) {
		say("%s: out of memory", d->name);
		real.close(h);
		free(d->tmp);
		free(d->raw);
		d->tmp = NULL;
		d->raw = NULL;
		return -ENOMEM;
	}
	d->codec = h;
	d->cch = ch;
	d->resync = 1;
	d->rounds = d->codec_xruns = 0;
	say("%s: codec %s open, %d ch S32_LE %u Hz, period %lu, buffer %lu; gadget %d ch %s", d->name,
	    cfg.codec_pcm, ch, d->rate, period, buffer, d->gch, d->gfmt == MIO_S16 ? "S16_LE" : "S32_LE");
	return 0;
}

/* Starts the codec afresh: after opening, after an xrun on either side. */
static void codec_restart(struct dir *d)
{
	snd_pcm_drop(d->codec);
	real.prepare(d->codec);
	mio_elastic_reset(&d->el, cfg.ring);
	if (d->stream == SND_PCM_STREAM_PLAYBACK) {
		size_t n = cfg.queue < d->frames ? cfg.queue : d->frames;
		memset(d->raw, 0, n * (size_t)d->cch * sizeof(int32_t));
		real.writei(d->codec, d->raw, n);
	}
	snd_pcm_start(d->codec);
	d->resync = 0;
}

static void status(struct dir *d)
{
	if (++d->rounds % LOG_EVERY == 0 && cfg.verbose)
		say("%s: ratio %+.2f ppm, fill %.0f of %.0f, %lu codec xruns, %lu underflows, %lu overflows",
		    d->name, (d->el.ratio - 1) * 1e6, d->el.fill_avg, d->el.target, d->codec_xruns,
		    d->el.underflows, d->el.overflows);
}

/* MPC wrote n frames to the gadget: send the mapped channels on to the codec. */
static void playback_tap(struct dir *d, const void *buf, size_t n)
{
	snd_pcm_sframes_t delay;
	if (d->resync)
		codec_restart(d);
	if (n > d->frames)
		n = d->frames;
	memset(d->tmp, 0, n * (size_t)d->cch * sizeof(float));
	for (int m = 0; m < d->nmap; m++)
		for (size_t f = 0; f < n; f++)
			d->tmp[f * d->cch + d->map[m].codec] +=
				cfg.gain * mio_get(buf, d->gfmt, f * d->gch + d->map[m].gadget);
	mio_elastic_push(&d->el, d->tmp, n);
	if (snd_pcm_delay(d->codec, &delay) < 0 || snd_pcm_state(d->codec) == SND_PCM_STATE_XRUN) {
		d->codec_xruns++;
		codec_restart(d);
		return;
	}
	long want = (long)cfg.queue - delay;
	if (want > (long)d->frames)
		want = (long)d->frames;
	if (want > 0) {
		mio_elastic_pull(&d->el, d->tmp, (size_t)want);
		for (long i = 0; i < want * d->cch; i++)
			mio_put(d->raw, MIO_S32, (size_t)i, d->tmp[i]);
		snd_pcm_sframes_t w = real.writei(d->codec, d->raw, (snd_pcm_uframes_t)want);
		if (w == -EPIPE) {
			d->codec_xruns++;
			codec_restart(d);
			return;
		}
		if (w > 0)
			delay += w;
	}
	mio_elastic_steer(&d->el, (double)delay);
	status(d);
}

/* MPC read n frames from the gadget: put the codec's inputs into the mapped channels. */
static void capture_insert(struct dir *d, void *buf, size_t n)
{
	if (d->resync)
		codec_restart(d);
	if (n > d->frames)
		n = d->frames;
	for (;;) {
		snd_pcm_sframes_t r = real.readi(d->codec, d->raw, (snd_pcm_uframes_t)d->frames);
		if (r == -EAGAIN || r == 0)
			break;
		if (r < 0) {
			d->codec_xruns++;
			codec_restart(d);
			break;
		}
		for (long i = 0; i < r * d->cch; i++)
			d->tmp[i] = mio_get(d->raw, MIO_S32, (size_t)i);
		mio_elastic_push(&d->el, d->tmp, (size_t)r);
		if ((size_t)r < d->frames)
			break;
	}
	mio_elastic_pull(&d->el, d->tmp, n);
	for (int m = 0; m < d->nmap; m++)
		for (size_t f = 0; f < n; f++)
			mio_put(buf, d->gfmt, f * d->gch + d->map[m].gadget, d->tmp[f * d->cch + d->map[m].codec]);
	snd_pcm_sframes_t avail = snd_pcm_avail_update(d->codec);
	mio_elastic_steer(&d->el, avail > 0 ? (double)avail : 0);
	status(d);
}

EXPORT int snd_pcm_open(snd_pcm_t **pcmp, const char *name, snd_pcm_stream_t stream, int mode)
{
	char id[32];
	pthread_once(&once, init);
	int err = real.open(pcmp, name, stream, mode);
	if (err < 0 || cfg.off || card_id(*pcmp, id, sizeof(id)) < 0 || strcmp(id, cfg.gadget_id))
		return err;
	struct dir *d = stream == SND_PCM_STREAM_PLAYBACK ? &play : &cap;
	pthread_mutex_lock(&lock);
	if (d->gadget)
		codec_close(d);
	d->gadget = *pcmp;
	pthread_mutex_unlock(&lock);
	say("MPC opened the gadget for %s as '%s'", d->name, name ? name : "?");
	return err;
}

EXPORT int snd_pcm_close(snd_pcm_t *pcm)
{
	pthread_once(&once, init);
	struct dir *d = dir_of(pcm);
	if (d) {
		/* Also lets MPC have the codec back when it switches to its internal audio. */
		pthread_mutex_lock(&lock);
		codec_close(d);
		d->gadget = NULL;
		pthread_mutex_unlock(&lock);
	}
	return real.close(pcm);
}

EXPORT int snd_pcm_hw_params(snd_pcm_t *pcm, snd_pcm_hw_params_t *params)
{
	pthread_once(&once, init);
	int err = real.hw_params(pcm, params);
	struct dir *d = dir_of(pcm);
	if (err < 0 || !d || !d->nmap)
		return err;
	snd_pcm_format_t fmt;
	snd_pcm_access_t access;
	unsigned ch, rate;
	snd_pcm_uframes_t buffer;
	snd_pcm_hw_params_get_format(params, &fmt);
	snd_pcm_hw_params_get_access(params, &access);
	snd_pcm_hw_params_get_channels(params, &ch);
	snd_pcm_hw_params_get_rate(params, &rate, NULL);
	snd_pcm_hw_params_get_buffer_size(params, &buffer);
	pthread_mutex_lock(&lock);
	codec_close(d);
	if (access != SND_PCM_ACCESS_RW_INTERLEAVED || (fmt != SND_PCM_FORMAT_S16_LE && fmt != SND_PCM_FORMAT_S32_LE)) {
		say("%s: gadget opened as %s, %s: passing it through", d->name, snd_pcm_access_name(access),
		    snd_pcm_format_name(fmt));
	} else {
		int ok = 1;
		for (int i = 0; i < d->nmap; i++)
			ok &= d->map[i].gadget < (int)ch && d->map[i].codec < 4;
		d->gch = (int)ch;
		d->gfmt = fmt == SND_PCM_FORMAT_S16_LE ? MIO_S16 : MIO_S32;
		d->rate = rate;
		if (!ok)
			say("%s: a channel pair is out of range (gadget has %u channels, codec up to 4)", d->name, ch);
		else
			codec_open(d, buffer);
	}
	pthread_mutex_unlock(&lock);
	return err;
}

EXPORT int snd_pcm_prepare(snd_pcm_t *pcm)
{
	pthread_once(&once, init);
	int err = real.prepare(pcm);
	struct dir *d = dir_of(pcm);
	if (d)
		d->resync = 1;
	return err;
}

EXPORT int snd_pcm_recover(snd_pcm_t *pcm, int err, int silent)
{
	pthread_once(&once, init);
	int r = real.recover(pcm, err, silent);
	struct dir *d = dir_of(pcm);
	if (d)
		d->resync = 1;
	return r;
}

EXPORT snd_pcm_sframes_t snd_pcm_writei(snd_pcm_t *pcm, const void *buf, snd_pcm_uframes_t size)
{
	pthread_once(&once, init);
	snd_pcm_sframes_t n = real.writei(pcm, buf, size);
	if (n > 0 && pcm == play.gadget && play.codec)
		playback_tap(&play, buf, (size_t)n);
	return n;
}

EXPORT snd_pcm_sframes_t snd_pcm_readi(snd_pcm_t *pcm, void *buf, snd_pcm_uframes_t size)
{
	pthread_once(&once, init);
	snd_pcm_sframes_t n = real.readi(pcm, buf, size);
	if (n > 0 && pcm == cap.gadget && cap.codec)
		capture_insert(&cap, buf, (size_t)n);
	return n;
}
