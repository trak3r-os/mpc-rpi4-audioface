// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_protocol.h"

#include <cstring>

namespace panel {
namespace {
constexpr size_t kMaxReplyBytes = 64 * 1024;
bool printable(const std::string& s) {
  for (unsigned char c : s)
    if (c < 0x20 || c > 0x7e) return false;
  return true;
}
}  // namespace

std::vector<uint8_t> encode_command(const std::string& text) {
  std::vector<uint8_t> out;
  if (text.empty() || !printable(text) || text.size() + 5 > kMaxCommandBytes) return out;
  out = {0xF0, 0x7D, 0x52, 0x41};
  out.insert(out.end(), text.begin(), text.end());
  out.push_back(0xF7);
  return out;
}

bool SysexAssembler::feed(const uint8_t* d, size_t n, std::string& text) {
  size_t i = 0;
  if (n && d[0] == 0xF0) { buf_.clear(); open_ = true; }
  else if (!open_) return false;
  for (; i < n; i++) {
    uint8_t c = d[i];
    if (c == 0xF7) {
      bool done = open_ && buf_.size() >= 4 && buf_[0] == 0xF0 && buf_[1] == 0x7D && buf_[2] == 0x52 && buf_[3] == 0x42;
      if (done) text.assign(buf_.begin() + 4, buf_.end());
      reset();
      return done;
    }
    if (c >= 0x80 && !(c == 0xF0 && i == 0)) { reset(); return false; }  // another status byte: not our reply
    buf_.push_back(c);
    if (buf_.size() > kMaxReplyBytes) { reset(); return false; }
  }
  return false;  // F7 still to come in a later event
}

std::string fit_text(const std::string& s, size_t max) {
  std::string t;
  for (unsigned char c : s) t += (c >= 0x20 && c <= 0x7e) ? static_cast<char>(c) : '?';
  if (t.size() > max) t = max > 3 ? t.substr(0, max - 3) + "..." : t.substr(0, max);
  return t;
}

bool valid_identity(const std::string& id) {
  if (id.empty() || id.size() > 100) return false;
  for (unsigned char c : id)
    if (c <= 0x20 || c > 0x7e) return false;
  return true;
}

std::string cmd_status() { return "status"; }

std::string cmd_mute(const std::string& id, bool out, bool on) {
  if (!valid_identity(id)) return "";
  return "mute " + id + (out ? " out " : " in ") + (on ? "on" : "off");
}

std::string cmd_volume(const std::string& id, bool out, int percent) {
  if (!valid_identity(id)) return "";
  if (percent < 0) percent = 0;
  if (percent > 100) percent = 100;
  return "volume " + id + (out ? " out " : " in ") + std::to_string(percent);
}

std::string cmd_name(const std::string& id, const std::string& text) {
  if (!valid_identity(id)) return "";
  std::string t = fit_text(text, 24);
  return t.empty() ? "name " + id : "name " + id + " " + t;
}

std::string cmd_preset(const char* verb, int slot) {
  if (slot < 1 || slot > 8) return "";
  if (std::strcmp(verb, "save") && std::strcmp(verb, "load") && std::strcmp(verb, "clear")) return "";
  return std::string("preset ") + verb + " " + std::to_string(slot);
}

}  // namespace panel
