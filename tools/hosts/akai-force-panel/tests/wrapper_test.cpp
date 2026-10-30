// SPDX-License-Identifier: GPL-3.0-or-later
// The plugin as MPC sees it: VSTPluginMain, the generated parameter table, the vendored wrapper and the engine over a
// fake MIDI link. Checks the host notifications (audioMasterAutomate / UpdateDisplay) and the command path.
#include <chrono>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <set>
#include <string>
#include <thread>

#include "fixtures.h"
#include "panel_layout.h"
#include "params.h"

using namespace panel;

extern "C" {
struct AEffect {
  int32_t magic;
  intptr_t (*dispatcher)(AEffect*, int32_t, int32_t, intptr_t, void*, float);
  void (*process)(AEffect*, float**, float**, int32_t);
  void (*setParameter)(AEffect*, int32_t, float);
  float (*getParameter)(AEffect*, int32_t);
  int32_t numPrograms, numParams, numInputs, numOutputs, flags;
  intptr_t resvd1, resvd2;
  int32_t initialDelay, realQualities, offQualities;
  float ioRatio;
  void *object, *user;
  int32_t uniqueID, version;
  void (*processReplacing)(AEffect*, float**, float**, int32_t);
  void (*processDoubleReplacing)(AEffect*, double**, double**, int32_t);
  char future[56];
};
AEffect* VSTPluginMain(intptr_t (*master)(AEffect*, int32_t, int32_t, intptr_t, void*, float));
}

static FakeIo* g_io = nullptr;
namespace panel {
std::unique_ptr<Io> make_alsa_io(const Conf&) {
  struct AutoIo : FakeIo { AutoIo() { present = true; } };
  AutoIo* io = new AutoIo;
  g_io = io;
  return std::unique_ptr<Io>(io);
}
}  // namespace panel

static int g_fail = 0, g_checks = 0;
#define CHECK(c)                                                                  \
  do {                                                                            \
    g_checks++;                                                                   \
    if (!(c)) { g_fail++; std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } \
  } while (0)

static std::set<int> g_automated;
static int g_automate_calls = 0, g_updates = 0;
static intptr_t master(AEffect*, int32_t op, int32_t index, intptr_t, void*, float) {
  if (op == 0) { g_automated.insert(index); g_automate_calls++; }
  if (op == 42) g_updates++;
  return 0;
}

static void run(AEffect* e, int ms) {
  static float l[128], r[128];
  float* out[2] = {l, r};
  for (int i = 0; i < ms / 5; i++) {
    e->processReplacing(e, nullptr, out, 128);
    for (int k = 0; k < 128; k++) CHECK(l[k] == 0.0f && r[k] == 0.0f);
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
}

static std::string display(AEffect* e, int idx) {
  char b[64] = {0};
  e->dispatcher(e, 7, idx, 0, b, 0);
  return b;
}

int main() {
  AEffect* e = VSTPluginMain(master);
  CHECK(e != nullptr);
  CHECK(e->numParams == kParams);
  CHECK(e->uniqueID == 0x5270506e);  // 'RpPn'
  auto t0 = std::chrono::steady_clock::now();
  char name[64] = {0};
  e->dispatcher(e, 45, 0, 0, name, 0);
  CHECK(std::string(name) == "rpi-audio Panel");
  e->dispatcher(e, 8, strip_param(0, F_IN_LEVEL), 0, name, 0);
  CHECK(std::string(name) == "S1 IN Level");

  // The host writes project values before the Pi is known: only local, and the Pi's values win.
  e->setParameter(e, strip_param(0, F_IN_LEVEL), 0.2f);
  run(e, 2000);
  CHECK(g_automated.count(strip_param(0, F_PRESENT)));
  CHECK(g_updates >= 1);
  CHECK(g_io->count("volume usb-aaaa:0001-MIX in 20") == 0);
  CHECK(display(e, P_LINK) == "44.1 kHz | 26x26");
  CHECK(display(e, strip_param(0, F_NAME)) == "Mixer");
  CHECK(display(e, strip_param(1, F_NAME)) == "Valeton GP-150");
  CHECK(display(e, strip_param(0, F_IN_LEVEL)) == "100");
  CHECK(display(e, strip_param(0, F_OUT_LEVEL)) == "80");
  CHECK(display(e, strip_param(2, F_IN_RANGE)) == "IN 9-20");
  CHECK(display(e, strip_param(4, F_NAME)).empty());
  CHECK(e->getParameter(e, strip_param(0, F_IN_LEVEL)) == 1.0f);
  CHECK(e->getParameter(e, strip_param(1, F_IN_MUTE)) == 1.0f);
  CHECK(e->getParameter(e, strip_param(1, F_KIND)) == 1.0f);          // custom name
  CHECK(e->getParameter(e, strip_param(0, F_PRESENT)) == 1.0f);
  CHECK(e->getParameter(e, strip_param(3, F_PRESENT)) == 0.0f);
  CHECK(e->getParameter(e, strip_param(0, F_IN_VIS)) == 0.5f);        // 1 of 0..2
  CHECK(display(e, P_PRESET_NAME) == "Live");
  CHECK(display(e, P_PRESET_NAME + 1) == "-");

  // Nothing is announced again while nothing changes.
  run(e, 200);
  int calls = g_automate_calls;
  run(e, 600);
  CHECK(g_automate_calls == calls);

  // The project's saved state.
  char* chunk = nullptr;
  intptr_t n = e->dispatcher(e, 23, 0, 0, &chunk, 0);
  CHECK(n > 0 && chunk && std::strstr(chunk, "onload=0"));
  const char* saved = "rpi-audio-panel 1 onload=3";
  e->dispatcher(e, 24, 0, static_cast<intptr_t>(std::strlen(saved) + 1), const_cast<char*>(saved), 0);
  CHECK(e->getParameter(e, P_ONLOAD) == 3.0f / 8.0f);

  // After the startup and restore locks, the user's changes go out as commands.
  while (std::chrono::steady_clock::now() - t0 < std::chrono::milliseconds(5600)) run(e, 100);
  CHECK(g_io->count("preset load 3") == 1);  // "On project load", once
  e->setParameter(e, strip_param(0, F_IN_LEVEL), 0.5f);
  run(e, 600);
  CHECK(g_io->count("volume usb-aaaa:0001-MIX in 50") == 1);
  CHECK(e->getParameter(e, strip_param(0, F_IN_LEVEL)) == 0.5f);
  e->setParameter(e, strip_param(0, F_OUT_MUTE), 1.0f);
  run(e, 400);
  CHECK(g_io->count("mute usb-aaaa:0001-MIX out on") == 1);

  // The name picker: tap opens it, a pick sends the name and closes it.
  e->setParameter(e, strip_param(1, F_KIND_OPEN), 1.0f);
  CHECK(e->getParameter(e, strip_param(1, F_KIND_OPEN)) == 1.0f);
  e->setParameter(e, strip_param(1, F_KIND), 1.0f / 14.0f);  // Guitar
  CHECK(e->getParameter(e, strip_param(1, F_KIND_OPEN)) == 0.0f);
  run(e, 400);
  CHECK(g_io->count("name usb-84ef:0186-GP Guitar") == 1);
  CHECK(display(e, strip_param(1, F_NAME)) == "Guitar");

  // Presets: a tap loads; with SAVE on, it saves and SAVE turns itself off.
  e->setParameter(e, P_PRESET, 1.0f);
  run(e, 400);
  CHECK(g_io->count("preset load 1") == 1);
  e->setParameter(e, P_SAVE, 1.0f);
  e->setParameter(e, P_PRESET + 1, 1.0f);
  run(e, 400);
  CHECK(g_io->count("preset save 2") == 1);
  CHECK(e->getParameter(e, P_SAVE) == 0.0f);
  CHECK(g_automated.count(P_SAVE));

  e->dispatcher(e, 1, 0, 0, nullptr, 0);  // effClose
  std::printf("%d checks, %d failed\n", g_checks, g_fail);
  return g_fail ? 1 : 0;
}
