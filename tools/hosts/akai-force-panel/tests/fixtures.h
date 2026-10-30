// SPDX-License-Identifier: GPL-3.0-or-later
// Test fixtures: status JSON builders and a scriptable MIDI link.
#pragma once
#include <algorithm>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <deque>
#include <mutex>
#include <string>
#include <vector>

#include "panel_io.h"

namespace panel {

// ---- helpers ----------------------------------------------------------------------------------------

inline std::string dir_json(int start, int ch, bool running, bool muted, const std::string& level,
                            const std::string& names = "", const std::string& blocked = "") {
  std::string s = "{\"client\":\"c\",\"channels\":" + std::to_string(ch) + ",\"rate\":48000,\"start\":" +
                  (start < 0 ? std::string("null") : std::to_string(start)) + ",\"running\":" + (running ? "true" : "false") +
                  ",\"muted\":" + (muted ? "true" : "false") + ",\"level\":" + level;
  if (!names.empty()) s += ",\"names\":[" + names + "]";
  if (!blocked.empty()) s += ",\"blocked\":\"" + blocked + "\"";
  return s + "}";
}

inline std::string device_json(const std::string& id, const std::string& name, const std::string& in,
                               const std::string& out) {
  std::string s = "{\"identity\":\"" + id + "\",\"card\":\"" + id.substr(0, 4) + "\",\"usbbus\":\"001/003\"";
  if (!name.empty()) s += ",\"name\":\"" + name + "\"";
  if (!in.empty()) s += ",\"in\":" + in;
  if (!out.empty()) s += ",\"out\":" + out;
  return s + "}";
}

inline std::string status_json(const std::vector<std::string>& devs, const std::string& presets = "") {
  std::string s = "{\"time\":\"2026-10-30 14:00:00\",\"host_playback_rate\":44100,\"host_capture_rate\":44100,"
                  "\"feeder\":\"jack\",\"jack_ready\":true,\"gadget_channels\":26,\"devices\":[";
  for (size_t i = 0; i < devs.size(); i++) s += (i ? "," : "") + devs[i];
  s += "],\"midi\":null";
  if (!presets.empty()) s += ",\"presets\":" + presets;
  return s + "}";
}

inline std::string three_devices() {
  return status_json(
      {device_json("usb-aaaa:0001-MIX", "Mixer", dir_json(1, 2, true, false, "100", "\"Main L\",\"Main R\""),
                   dir_json(3, 2, true, false, "80")),
       device_json("usb-84ef:0186-GP", "Valeton GP-150",
                   dir_json(3, 6, true, true, "null", "\"Out L\",\"Out R\",\"\",\"\",\"\",\"\""),
                   dir_json(5, 4, true, false, "100")),
       device_json("usb-cccc:0003-TRK", "Tracker", dir_json(9, 12, true, false, "100"), dir_json(9, 2, true, false, "100"))},
      "[{\"slot\":1,\"name\":\"Live\",\"saved\":\"2026-10-30 13:40\"},{\"slot\":3,\"name\":\"\",\"saved\":\"x\"}]");
}

struct FakeIo : Io {
  std::mutex mu;
  std::condition_variable cv;
  std::deque<std::vector<uint8_t>> inbox;
  std::vector<std::string> sent;
  std::atomic<bool> present{false}, linked{false};
  std::atomic<int> connects{0};
  std::string status = three_devices();

  bool connect() override {
    connects++;
    if (!present) return false;
    linked = true;
    return true;
  }
  bool alive() override { return present; }
  void disconnect() override { linked = false; }
  bool send(const std::vector<uint8_t>& m) override {
    std::string text(m.begin() + 4, m.end() - 1);
    std::lock_guard<std::mutex> lk(mu);
    sent.push_back(text);
    std::string reply = text == "status" ? status : "ok";
    std::vector<uint8_t> f = {0xF0, 0x7D, 0x52, 0x42};
    f.insert(f.end(), reply.begin(), reply.end());
    f.push_back(0xF7);
    for (size_t i = 0; i < f.size(); i += 90)  // delivered in pieces
      inbox.emplace_back(f.begin() + i, f.begin() + std::min(f.size(), i + 90));
    cv.notify_all();
    return true;
  }
  int recv(std::vector<uint8_t>& chunk, int timeout_ms) override {
    std::unique_lock<std::mutex> lk(mu);
    cv.wait_for(lk, std::chrono::milliseconds(std::min(timeout_ms, 5)), [this] { return !inbox.empty(); });
    if (inbox.empty()) return 0;
    chunk = inbox.front();
    inbox.pop_front();
    return 1;
  }
  int count(const std::string& s) {
    std::lock_guard<std::mutex> lk(mu);
    int n = 0;
    for (auto& x : sent) n += x == s;
    return n;
  }
};


}  // namespace panel
