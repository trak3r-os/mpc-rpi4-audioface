// SPDX-License-Identifier: GPL-3.0-or-later
// Adapter: the sd88me wrapper (wrapper/engine.h) drives this as an "engine". It makes no sound; it exists for its
// parameters, which the skin shows and the Q-Links drive.
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>

extern "C" {
#include "engine.h"
}
#include "panel_engine.h"

using namespace panel;

namespace {

struct Instance {
  std::unique_ptr<Engine> engine;
  uint32_t pending[kWords] = {};  // changes taken from the core and not yet handed to the wrapper
};

void* create(const char* data_dir) {
  Conf conf = load_conf(data_dir ? data_dir : "");
  auto log = [](const std::string& m) { std::fprintf(stderr, "rpi-audio panel: %s\n", m.c_str()); };
  Instance* in = new Instance;
  in->engine.reset(new Engine(make_alsa_io(conf), CoreConfig(), log));
  return in;
}

void destroy(void* p) { delete static_cast<Instance*>(p); }
void midi(void*, const uint8_t*, int) {}
void render(void*, int16_t* out, int frames) { std::memset(out, 0, sizeof(int16_t) * 2 * static_cast<size_t>(frames)); }

Core& core_of(void* p) { return static_cast<Instance*>(p)->engine->core(); }

// The wrapper sends values as text: an option's index, or the value in the parameter's own range.
void set_param(void* p, const char* key, const char* val) {
  if (!std::strcmp(key, "state")) {
    core_of(p).load_state(val);
    return;
  }
  int i = key_index(key);
  if (i < 0 || is_text(i)) return;
  double v = std::strtod(val, nullptr);
  if (std::isfinite(v)) core_of(p).set_param(i, static_cast<int>(std::lround(v)));
}

int get_param(void* p, const char* key, char* buf, int n) {
  if (n < 1) return 0;
  Core& c = core_of(p);
  if (!std::strcmp(key, "state")) {
    std::snprintf(buf, n, "%s", c.state_string().c_str());
    return static_cast<int>(std::strlen(buf));
  }
  int i = key_index(key);
  if (i < 0) return -1;
  if (is_text(i)) {
    c.get_text(i, buf, n);
    return static_cast<int>(std::strlen(buf)) + 1;  // > 0 even for empty text
  }
  std::snprintf(buf, n, "%d", c.get_value(i));
  return static_cast<int>(std::strlen(buf));
}

}  // namespace

// What changed on its own (the Pi's status, a reply): the wrapper asks once per block, one key per call, under its
// engine lock, and tells the host. Texts are left out: the wrapper polls those itself and asks for an UpdateDisplay.
extern "C" int mpc_engine_changed(void* p, char* key, int len) {
  Instance* in = static_cast<Instance*>(p);
  for (int pass = 0; pass < 2; pass++) {
    for (int w = 0; w < kWords; w++)
      while (in->pending[w]) {
        int i = w * 32 + __builtin_ctz(in->pending[w]);
        in->pending[w] &= in->pending[w] - 1;
        if (i >= kParams || is_text(i)) continue;
        key_name(i, key, len);
        return 1;
      }
    if (pass == 0) core_of(p).poll_changes(in->pending, kWords);
  }
  return 0;
}

extern "C" const mpc_engine_t* mpc_engine(void) {
  static const mpc_engine_t api = {create, destroy, midi, set_param, get_param, render, nullptr, nullptr};
  return &api;
}
