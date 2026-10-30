// SPDX-License-Identifier: GPL-3.0-or-later
// rpi-audiod `status` -> what the panel shows: strips, preset labels, link readout.
#pragma once
#include <string>
#include <vector>

#include "panel_layout.h"

namespace panel {

struct DirStatus {
  bool present = false;
  int channels = 0;
  int start = -1;  // first gadget channel (1-based); -1 = parked (JSON null)
  bool running = false, muted = false, blocked = false;
  int level = -1;  // -1 = unknown
  std::vector<std::string> names;
};

struct DeviceStatus {
  std::string identity, card, name;
  DirStatus in, out;
};

struct Status {
  int playback_rate = 0, capture_rate = 0, gadget_channels = 0;
  std::vector<DeviceStatus> devices;
  bool preset_saved[kPresets] = {};
  std::string preset_name[kPresets];
};

// False if `text` is not a JSON object.
bool parse_status(const std::string& text, Status& out);

enum class Link { NotFound, Connecting, NoReply, Ok };

struct StripView {
  bool present = false;
  int in_vis = 0, out_vis = 0;  // 0 hidden, 1 shown, 2 dimmed (device present, no such direction)
  std::string identity, name, state, in_range, in_names, out_range, out_names;
  int in_level = 100, out_level = 100, in_mute = 0, out_mute = 0, kind = 0;
};

struct View {
  std::string link;
  std::string preset[kPresets];
  StripView strip[kStrips];
};

// Devices ordered for the strips: by IN start channel, then OUT start; parked ones last.
std::vector<const DeviceStatus*> order_devices(const Status& s);
std::string link_text(Link link, const Status& s);
View make_view(Link link, const Status& s);

}  // namespace panel
