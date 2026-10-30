// SPDX-License-Identifier: GPL-3.0-or-later
// The MIDI side of the panel: one duplex ALSA sequencer port wired to the rpi-audio control cable.
#pragma once
#include <cstdint>
#include <memory>
#include <string>
#include <vector>

namespace panel {

struct Conf {
  std::string client = "rpi-audio";          // sequencer client name of the rpi-audio gadget
  std::string port = "rpi-audio MIDI 1";     // control port name; the client's first port if it is not found
};

// panel.conf: "key = value" lines, '#' comments. Unknown keys are ignored.
Conf parse_conf(const std::string& text);
Conf load_conf(const std::string& dir);

class Io {
 public:
  virtual ~Io() {}
  // Finds the client and subscribes both ways. False if it is not there (retry later).
  virtual bool connect() = 0;
  // Still there? Checked every couple of seconds while connected.
  virtual bool alive() = 0;
  virtual void disconnect() = 0;
  virtual bool send(const std::vector<uint8_t>& sysex) = 0;
  // Waits up to timeout_ms for one SysEx event's bytes: 1 = got `chunk`, 0 = nothing, -1 = error.
  virtual int recv(std::vector<uint8_t>& chunk, int timeout_ms) = 0;
};

// The real ALSA implementation, or one that never connects when built without ALSA (PANEL_NO_ALSA).
std::unique_ptr<Io> make_alsa_io(const Conf& conf);

}  // namespace panel
