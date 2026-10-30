// SPDX-License-Identifier: GPL-3.0-or-later
// Adapter: the sd88me wrapper (wrapper/engine.h) drives this as an "engine". It makes no sound; it exists for its
// parameters, which the skin shows and the Q-Links drive.
#include <cmath>
#include <cstdio>
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

void set_param(void* p, const char* key, const char* val) {
  if (!std::strcmp(key, "state")) core_of(p).load_state(val);
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

int poll_changes(void* p, uint32_t* changed, int nwords) { return core_of(p).poll_changes(changed, nwords); }

}  // namespace

// The wrapper's typed-parameter path (ENGINE_TYPED_PARAMETERS): numeric values without string round trips.
extern "C" int engine_get_physical(void* inst, int index, float* value) {
  if (index < 0 || index >= kParams) return 0;
  *value = is_text(index) ? 0.0f : static_cast<float>(core_of(inst).get_value(index));
  return 1;
}

extern "C" void engine_set_physical(void* inst, int index, float physical) {
  if (!std::isfinite(physical)) return;
  core_of(inst).set_param(index, static_cast<int>(std::lround(physical)));
}

extern "C" const mpc_engine_t* mpc_engine(void) {
  static const mpc_engine_t api = {create, destroy, midi, set_param, get_param, render, nullptr, poll_changes};
  return &api;
}
