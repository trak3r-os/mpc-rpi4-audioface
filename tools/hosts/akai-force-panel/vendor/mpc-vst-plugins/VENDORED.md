# Vendored: sd88me/mpc-vst-plugins (MIT)

Upstream: https://github.com/sd88me/mpc-vst-plugins, base commit `faae55acfbf3ccac88d15df8ab3c45f74002e91c`.
Copied from `/home/anortes/Code/barsiren-mcp/vendor/mpc-vst-plugins/` (the user's MIT project Dub Force Siren), not
from upstream's current head, because that copy is the one running on the user's Force and it carries fixes this
panel needs: lock-free atomics for the parameter shadow, popup and refresh state, input validation, the typed-parameter
hook and the deferred Q-Link refresh. Upstream's head (7150437 when checked) has moved on a lot (an 890-line wrapper,
a different installer); not adopted here, since there is no device evidence for it yet.

Files: `wrapper/{engine.h,plugin_dir.h,popup.h,vst2_wrap.c}`, `wrapper/parameter_mapping.h` (barsiren's `src/`),
`tools/{gen_vst.py,params.py,release.py}`, `tools/release/{install.sh,uninstall.sh,plugin_list.awk}`. Not vendored:
the skin generator (`shadow_skin.py` and friends); `skin.py` writes this plugin's skin itself.

## Changes made for rpi-audio Panel

1. `wrapper/vst2_wrap.c`: the typed-parameter hook is generic. `DUB_TYPED_PARAMETERS` is now
   `ENGINE_TYPED_PARAMETERS`, and `dub_force_get_physical` / `dub_force_set_physical` are now
   `engine_get_physical` / `engine_set_physical` (renames only).
2. `wrapper/engine.h`: `mpc_engine_t` gains a last member `poll_changes(inst, changed, nwords)`. NULL for engines
   that do not need it.
3. `wrapper/vst2_wrap.c`, `housekeeping()` (called from `processReplacing`): if `poll_changes` is set, call it; for
   every parameter it flags, `audioMasterAutomate(i, get_norm(i))`; if it reports a text change,
   `audioMasterUpdateDisplay`. Upstream's wrapper only notifies the host from inside `setParameter`, so a value that an
   engine thread changes on its own never reached the screen. Nothing runs when nothing changed.

Everything else is as in barsiren-mcp.
