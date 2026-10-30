// SPDX-License-Identifier: GPL-3.0-or-later
// rpi-audiod control protocol (docs/MIDI.md): text SysEx over the control cable, and the command texts.
#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <vector>

namespace panel {

constexpr size_t kMaxCommandBytes = 200;

// F0 7D 52 41 <text> F7. Empty if the text is not printable ASCII or the message would exceed 200 bytes.
std::vector<uint8_t> encode_command(const std::string& text);

// Reassembles a reply (F0 7D 52 42 <text> F7) that the sequencer may deliver in several SysEx events.
class SysexAssembler {
 public:
  // Feeds one event's bytes. True when a whole reply has arrived; `text` is then its payload.
  bool feed(const uint8_t* data, size_t n, std::string& text);
  void reset() { buf_.clear(); open_ = false; }

 private:
  std::vector<uint8_t> buf_;
  bool open_ = false;
};

// Printable ASCII only (others become '?'), cut to `max` bytes with "..." when it was longer.
std::string fit_text(const std::string& s, size_t max);
// An identity is a single token of printable ASCII.
bool valid_identity(const std::string& id);

// Command texts; empty string when an argument is invalid.
std::string cmd_status();
std::string cmd_mute(const std::string& id, bool out, bool on);
std::string cmd_volume(const std::string& id, bool out, int percent);
std::string cmd_name(const std::string& id, const std::string& text);  // empty text clears the name
std::string cmd_preset(const char* verb, int slot);                    // "save", "load" or "clear", slot 1..8

}  // namespace panel
