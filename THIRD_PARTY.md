# Third-party code and assets

Reused code keeps its own licence. Everything else in the repository is GPL-3.0-or-later.

## rpi-audio Panel (`tools/hosts/akai-force-panel/`)

### mpc-vst-plugins (MIT)

- Source: https://github.com/sd88me/mpc-vst-plugins, Copyright (c) 2026 sd88me, MIT. Licence copy:
  `tools/hosts/akai-force-panel/vendor/mpc-vst-plugins/LICENSE`.
- What: the VST2 wrapper (`wrapper/`), the parameter-table generator (`tools/gen_vst.py`, `tools/params.py`) and
  the packager and installer (`tools/release.py`, `tools/release/`).
- Taken from the copy vendored in the user's own MIT project `barsiren-mcp` (Dub Force Siren by no3z), which is
  upstream commit `faae55acfbf3ccac88d15df8ab3c45f74002e91c` plus that project's fixes (atomics, typed parameters,
  input validation, Q-Link refresh). It runs on the Force today. `wrapper/parameter_mapping.h` is that project's own
  file. Changes made here are listed in `vendor/mpc-vst-plugins/VENDORED.md`.
- Also adapted from `barsiren-mcp` (MIT): the shape of the native skin generator (`skin.py`: TUI.json components,
  Q-Link map layout, filmstrip faders) and the armhf build and ABI check (`build.sh`, `Dockerfile.arm`).
- The format facts behind the skin come from sd88me's `docs/` (MIT) as summarised in `barsiren-mcp/docs/MPC_UI_REFERENCE.md`.
  No stock MPC or Akai asset is copied.

### Titillium Web (SIL Open Font License 1.1)

- Copyright (c) 2009-2011 Accademia di Belle Arti di Urbino and students of MA course of Visual design.
- `tools/hosts/akai-force-panel/fonts/`, with `OFL.txt`; copied from sd88me's `tools/html_art/fonts/`.
- Used to bake the static labels into the skin images and to draw the desktop previews. MPC's own live labels use the
  same face. The fonts are not shipped in the plugin package; its `notices/` folder carries the OFL text.
