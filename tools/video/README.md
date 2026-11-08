# Overview video generator

Builds `rpi5-audioface-overview.mp4`: an animated explainer (1920x1080, 25 fps, about 3 minutes, H.264 + AAC) with a quiet
procedural music bed. The first part explains the project for any USB host; the last part, titled "Example host: Akai Force",
shows the first host we tested, its optional Panel plugin, and the separate add-on that brings the Force's own outputs back.

Every frame is rendered from this repository: Pillow draws the illustrations, cables and flowing signal dots, repository
screenshots (`docs/img/`, `docs/manual/img/`) get animated zoom and pan, and `music.py` synthesises the music.
No network, no Pi and no downloaded assets are needed.

## Rebuild

```sh
sudo apt install ffmpeg python3-pil python3-numpy fonts-dejavu-core
python3 tools/video/make-overview.py             # -> out/video/rpi5-audioface-overview.mp4 (a few minutes on 16+ cores)
python3 tools/video/make-overview.py --small     # also out/video/rpi5-audioface-overview-9mb.mp4 (720p, two-pass, < 9 MB)
python3 tools/video/make-overview.py --still 31  # one PNG at second 31 in out/video/ (handy while editing a scene)
```

Frames are rendered in parallel (one process per core) at 2x supersampling and piped straight into ffmpeg.
`out/` is git-ignored: the MP4s are not committed.

## Files

- `make-overview.py`: one function per scene, `s_xxx(canvas, t)`, where `t` is seconds since the scene started.
  `SCENES` lists them with their durations, and scenes crossfade for 0.5 s. Also the ffmpeg encoding and the CLI.
- `draw.py`: the drawing kit. A small canvas with transforms and alpha, easing helpers, cables that draw themselves, flowing
  signal dots (one colour in, another out), and the illustrations (Pi, laptop, mixer, synth, pedal, speaker, OLED unit,
  encoder, the example host...).
- `music.py`: an upbeat loop at 104 BPM (soft kick, offbeat hats, plucky bass, chord stabs and a simple pentatonic bell motif).
  Fixed random seed, so the music is identical on every build. It fades in and out and stays at background level.

## Editing

- Change a scene's length in `SCENES`; `TOTAL`, the scene start times and the music length follow automatically.
- Keep the film generic: host-specific material belongs only in the "Example host" scenes at the end.
- Most OLED screens are cropped from `docs/manual/img/`; the USB ports screen is rendered by `bridge/rpi-audio-ui`.
