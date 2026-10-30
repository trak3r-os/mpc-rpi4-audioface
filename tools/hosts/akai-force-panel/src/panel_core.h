// SPDX-License-Identifier: GPL-3.0-or-later
// Panel logic without threads or I/O: user intents -> commands, status -> published parameter values.
// The worker thread calls link_up/link_down/on_reply/tick/next_command; any thread may call set_param,
// get_value, get_text and poll_changes (lock-free, except get_text which only waits on a memcpy).
#pragma once
#include <atomic>
#include <cstdint>
#include <functional>
#include <mutex>
#include <string>
#include <vector>

#include "panel_layout.h"
#include "panel_model.h"

namespace panel {

struct CoreConfig {
  int hold_ms = 1500;          // keep a local value this long after a local change
  int send_hold_ms = 2000;     // ... and this long after its command went out (the Pi applies it in 1-2 s)
  int debounce_ms = 100;       // level changes are sent at most this often per control
  int min_gap_ms = 100;        // at most 10 commands per second overall
  int status_ms = 1000;        // status poll period
  int reply_timeout_ms = 4000; // no reply for this long: "No reply"
  int startup_lock_ms = 3000;  // ignore the host's parameter writes this long after creation (project restore)
  int chunk_lock_ms = 2000;    // ... and after the host restores the saved state
  int error_ms = 4000;         // show a command error in the link readout this long
  int retry_ms = 2000;         // look for the Pi again / check it is still there (used by Engine)
};

// Pending commands: a new command with the same key replaces the queued one (keeping its due time, so a
// dragged fader still gets through every debounce period); one command per min_gap_ms.
class CommandQueue {
 public:
  void push(const std::string& key, const std::string& cmd, int64_t due, int param);
  bool pop(int64_t now, int min_gap_ms, std::string& cmd, std::string* key, int* param);
  void clear() { items_.clear(); }
  size_t size() const { return items_.size(); }

 private:
  struct Item { std::string key, cmd; int64_t due; uint64_t seq; int param; };
  std::vector<Item> items_;
  uint64_t seq_ = 0;
  int64_t last_sent_ = -(1LL << 40);
};

class Core {
 public:
  using Log = std::function<void(const std::string&)>;
  using Clock = std::function<int64_t()>;
  explicit Core(CoreConfig cfg = {}, Log log = {}, Clock clock = {});

  void begin(int64_t now);
  const CoreConfig& config() const { return cfg_; }

  // Any thread.
  void set_param(int i, int v);
  int get_value(int i) const;
  bool get_text(int i, char* out, int n) const;
  int poll_changes(uint32_t* words, int nwords);  // params changed since the last call; 1 if a text changed
  std::string state_string() const;               // what the project stores
  void load_state(const std::string& s);          // project restore

  // Worker thread.
  void link_up(int64_t now);
  void link_down(int64_t now);
  void on_reply(const std::string& text, int64_t now);
  void tick(int64_t now);
  bool next_command(int64_t now, std::string& out);
  Link link() const { return link_; }
  bool synced() const { return synced_; }  // either thread
  const std::string& strip_identity(int s) const { return strip_id_[s]; }

 private:
  void republish(int64_t now);
  void consume(int64_t now);
  void handle(int i, int v, int64_t now);
  void handle_preset(int slot, int64_t now);
  void queue(const std::string& key, const std::string& cmd, int64_t now, int param, bool debounce);
  void mark(int i);
  void note(const std::string& msg) const { if (log_) log_(msg); }

  CoreConfig cfg_;
  Log log_;
  Clock clock_;

  // shared
  std::atomic<int> vals_[kParams];
  std::atomic<int> user_[kParams];
  std::atomic<uint32_t> touched_[kWords], dirty_bits_[kWords];
  std::atomic<int> taps_[kPresets];
  std::atomic<bool> text_dirty_{false};
  std::atomic<int64_t> lock_until_{0};
  mutable std::mutex mu_, reader_mu_;       // mu_: texts_, written by the worker; reader_mu_: cache_
  char texts_[kTexts][kTextMax + 1];
  mutable char cache_[kTexts][kTextMax + 1];

  // worker only
  Status status_;
  std::atomic<Link> link_{Link::NotFound};
  std::atomic<bool> synced_{false};
  bool dirty_ = true, holds_active_ = false, onload_pending_ = true;
  int64_t next_status_ = 0, last_reply_ = 0, error_until_ = 0;
  std::string error_text_;
  CommandQueue q_;
  int last_told_[kParams];
  int held_[kParams];
  int64_t hold_until_[kParams];
  std::string name_override_[kStrips];
  int64_t override_until_[kStrips];
  std::string strip_id_[kStrips];
};

}  // namespace panel
