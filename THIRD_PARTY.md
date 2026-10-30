# Third-party code and assets

Reused code keeps its own licence. Everything else in the repository is GPL-3.0-or-later.

## mpc-vst-plugins (MIT), in `tools/hosts/vendor/mpc-vst-plugins/`

- Source: https://github.com/sd88me/mpc-vst-plugins, Copyright (c) 2026 sd88me, MIT. Licence copy:
  `tools/hosts/vendor/mpc-vst-plugins/LICENSE`.
- What: the VST2 wrapper (`wrapper/`), the parameter-table generator (`tools/gen_vst.py`, `tools/params.py`), the plugin
  and addin packagers and installers (`tools/release.py`, `tools/release_addin.py`, `tools/release/`) and the catalog
  checker (`tools/catalog_check.py`, `tools/skin_compat.py`, `tools/skin_roles_2x.json`).
- Copied unmodified from upstream by `tools/hosts/vendor/sync-mpc-vst-plugins.sh`; the commit is in `VENDORED.md`.
- Used by the rpi-audio Panel (`tools/hosts/akai-force-panel/`, which links the wrapper into its plugin and ships
  sd88me's installer in its zip) and by the internal I/O add-on (`tools/hosts/akai-force-internal-io/`, whose zip ships
  sd88me's addin installer).

## rpi-audio Panel (`tools/hosts/akai-force-panel/`)

- Adapted from `barsiren-mcp` (MIT): the shape of the native skin generator (`skin.py`: TUI.json components,
  Q-Link map layout, filmstrip faders) and the armhf build and ABI check (`build.sh`, `Dockerfile.arm`).
- The format facts behind the skin come from sd88me's `docs/` (MIT) as summarised in `barsiren-mcp/docs/MPC_UI_REFERENCE.md`.
  No stock MPC or Akai asset is copied.

### Titillium Web (SIL Open Font License 1.1)

- Copyright (c) 2009-2011 Accademia di Belle Arti di Urbino and students of MA course of Visual design.
- `tools/hosts/akai-force-panel/fonts/`, with `OFL.txt`; copied from sd88me's `tools/html_art/fonts/`.
- Used to bake the static labels into the skin images and to draw the desktop previews. MPC's own live labels use the
  same face. The fonts are not shipped in the plugin package; its `notices/` folder carries the OFL text.
