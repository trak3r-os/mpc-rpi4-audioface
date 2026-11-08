# Overview video generator

Builds `rpi5-audioface-overview.mp4`: 16 silent slides (1920x1080, about 2:45, H.264) with a quiet procedural music bed (AAC).
Everything is generated from this repository: diagrams are drawn with Pillow, OLED screens are cropped from `docs/manual/img/`
or rendered by the project's own OLED renderer (`bridge/rpi-audio-ui`), and the music is synthesised by `music.py`.
No network, no Pi and no downloaded assets are needed.

## Rebuild

```sh
sudo apt install ffmpeg python3-pil python3-numpy fonts-dejavu-core
python3 tools/video/make-overview.py            # -> out/video/rpi5-audioface-overview.mp4 (about 3 minutes to encode)
python3 tools/video/make-overview.py --frames   # only the slide PNGs in out/video/build/ (about 20 seconds)
python3 tools/video/music.py out/video/music.wav 60   # just the music bed
```

`out/` is git-ignored: the MP4 and the frames are not committed.

## Editing

- `SLIDES` in `make-overview.py` lists each slide: kicker, title, the seconds of every reveal step, and its drawing function.
  A slide with N steps is rendered N times, each adding more content, and ffmpeg crossfades the steps.
- `SPEED` scales all timings. The music length follows the total duration automatically.
- `music.py` uses a fixed random seed, so the music is the same on every build.
