// SPDX-License-Identifier: GPL-3.0-or-later
// Parameter layout of the panel plugin. Saved projects and Q-Link maps bind by index: append only, never reorder.
// panel_def.py mirrors this; tests/unit.cpp checks the generated params.h against it.
#pragma once
#include <cstdio>
#include <cstring>

namespace panel {

constexpr int kStrips = 6, kPresets = 8;
constexpr int kTextMax = 23;  // MPC's effGetParamDisplay buffer is 24 bytes
constexpr int kKindCount = 15, kKindCustom = 14;

inline const char* const kKindNames[kKindCount] = {"Default", "Guitar", "Bass", "Synth", "Keys", "Drums",
                                                    "Drum machine", "Sampler", "Vocal", "Mic", "Mixer", "Line",
                                                    "FX", "Tracker", "Custom"};

// Per-strip fields, in index order within a strip.
enum Field {
  F_NAME, F_STATE, F_PRESENT, F_IN_VIS, F_OUT_VIS, F_IN_RANGE, F_IN_NAMES, F_IN_LEVEL, F_IN_MUTE,
  F_OUT_RANGE, F_OUT_NAMES, F_OUT_LEVEL, F_OUT_MUTE, F_KIND, F_KIND_OPEN, kFields
};

constexpr int P_LINK = 0, P_PRESET = 1, P_PRESET_NAME = 9, P_SAVE = 17, P_ONLOAD = 18, P_STRIP = 19;
constexpr int kParams = P_STRIP + kStrips * kFields;
constexpr int kWords = (kParams + 31) / 32;

constexpr int strip_param(int s, int f) { return P_STRIP + s * kFields + f; }

enum Kind { K_TEXT, K_TRIGGER, K_LEVEL, K_MUTE, K_KIND, K_VIS, K_LOCAL, K_POPUP };

constexpr Kind kind_of(int i) {
  if (i == P_LINK) return K_TEXT;
  if (i >= P_PRESET && i < P_PRESET + kPresets) return K_TRIGGER;
  if (i >= P_PRESET_NAME && i < P_PRESET_NAME + kPresets) return K_TEXT;
  if (i == P_SAVE || i == P_ONLOAD) return K_LOCAL;
  if (i < P_STRIP || i >= kParams) return K_LOCAL;
  switch ((i - P_STRIP) % kFields) {
    case F_NAME: case F_STATE: case F_IN_RANGE: case F_IN_NAMES: case F_OUT_RANGE: case F_OUT_NAMES: return K_TEXT;
    case F_IN_LEVEL: case F_OUT_LEVEL: return K_LEVEL;
    case F_IN_MUTE: case F_OUT_MUTE: return K_MUTE;
    case F_KIND: return K_KIND;
    case F_KIND_OPEN: return K_POPUP;
    default: return K_VIS;
  }
}
constexpr bool is_text(int i) { return kind_of(i) == K_TEXT; }
constexpr int strip_of(int i) { return i >= P_STRIP && i < kParams ? (i - P_STRIP) / kFields : -1; }
constexpr int field_of(int i) { return i >= P_STRIP && i < kParams ? (i - P_STRIP) % kFields : -1; }

// Text parameters are numbered 0.. in index order (the text table slot).
constexpr int text_count() { int n = 0; for (int i = 0; i < kParams; i++) n += is_text(i); return n; }
constexpr int kTexts = text_count();
constexpr int text_slot(int i) { int n = 0; for (int j = 0; j < i; j++) n += is_text(j); return n; }

// Parameter key (as in params.json) of index i; "" if out of range.
inline const char* key_name(int i, char* buf, int n) {
  static const char* const f[kFields] = {"name", "state", "present", "in_vis", "out_vis", "in_range", "in_names",
                                         "in_level", "in_mute", "out_range", "out_names", "out_level", "out_mute",
                                         "kind", "kind__open"};
  buf[0] = 0;
  if (i == P_LINK) std::snprintf(buf, n, "link");
  else if (i >= P_PRESET && i < P_PRESET + kPresets) std::snprintf(buf, n, "preset_%d", i - P_PRESET + 1);
  else if (i >= P_PRESET_NAME && i < P_PRESET_NAME + kPresets) std::snprintf(buf, n, "preset_name_%d", i - P_PRESET_NAME + 1);
  else if (i == P_SAVE) std::snprintf(buf, n, "save");
  else if (i == P_ONLOAD) std::snprintf(buf, n, "onload");
  else if (i >= P_STRIP && i < kParams) std::snprintf(buf, n, "s%d_%s", strip_of(i) + 1, f[field_of(i)]);
  return buf;
}

// Index of a parameter key, -1 if unknown.
inline int key_index(const char* key) {
  char b[32];
  for (int i = 0; i < kParams; i++)
    if (!std::strcmp(key_name(i, b, sizeof b), key)) return i;
  return -1;
}

}  // namespace panel
