// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_core.h"

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <cstring>
#include <thread>

#include "panel_protocol.h"

namespace panel {

// ---- CommandQueue ----------------------------------------------------------------------------------

void CommandQueue::push(const std::string& key, const std::string& cmd, int64_t due, int param) {
  for (Item& it : items_)
    if (it.key == key) {
      it.cmd = cmd;
      it.param = param;
      it.due = std::min(it.due, due);
      return;
    }
  items_.push_back({key, cmd, due, seq_++, param});
}

bool CommandQueue::pop(int64_t now, int min_gap_ms, std::string& cmd, std::string* key, int* param) {
  if (now - last_sent_ < min_gap_ms) return false;
  size_t best = items_.size();
  for (size_t i = 0; i < items_.size(); i++) {
    if (items_[i].due > now) continue;
    if (best == items_.size() || items_[i].due < items_[best].due ||
        (items_[i].due == items_[best].due && items_[i].seq < items_[best].seq))
      best = i;
  }
  if (best == items_.size()) return false;
  cmd = items_[best].cmd;
  if (key) *key = items_[best].key;
  if (param) *param = items_[best].param;
  items_.erase(items_.begin() + best);
  last_sent_ = now;
  return true;
}

// ---- Core ------------------------------------------------------------------------------------------

namespace {
int64_t steady_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch())
      .count();
}
bool is_local(int i) { return kind_of(i) == K_LOCAL; }
}  // namespace

Core::Core(CoreConfig cfg, Log log, Clock clock) : cfg_(cfg), log_(std::move(log)), clock_(std::move(clock)) {
  if (!clock_) clock_ = steady_ms;
  for (int i = 0; i < kParams; i++) {
    vals_[i] = 0;
    user_[i] = 0;
    last_told_[i] = -1;
    held_[i] = 0;
    hold_until_[i] = 0;
  }
  for (int w = 0; w < kWords; w++) { touched_[w] = 0; dirty_bits_[w] = 0; }
  for (int k = 0; k < kPresets; k++) taps_[k] = 0;
  for (int s = 0; s < kStrips; s++) override_until_[s] = 0;
  std::memset(texts_, 0, sizeof texts_);
  std::memset(cache_, 0, sizeof cache_);
}

void Core::begin(int64_t now) {
  lock_until_ = now + cfg_.startup_lock_ms;
  republish(now);  // the starting values are what the host already knows: nothing to announce yet
  for (int w = 0; w < kWords; w++) dirty_bits_[w] = 0;
  text_dirty_ = false;
}

void Core::set_param(int i, int v) {
  if (i < 0 || i >= kParams) return;
  switch (kind_of(i)) {
    case K_LOCAL:
      if (i == P_SAVE && clock_() < lock_until_) return;  // not a project-restore value
      vals_[i] = i == P_ONLOAD ? std::max(0, std::min(v, kPresets)) : (v ? 1 : 0);
      return;
    case K_TRIGGER:
      if (v > 0) taps_[i - P_PRESET]++;
      return;
    case K_LEVEL: case K_MUTE: case K_KIND:
      user_[i] = v;
      touched_[i >> 5].fetch_or(1u << (i & 31));
      return;
    default:
      return;
  }
}

int Core::get_value(int i) const { return i >= 0 && i < kParams ? vals_[i].load() : 0; }

bool Core::get_text(int i, char* out, int n) const {
  if (n < 1) return false;
  out[0] = 0;
  if (i < 0 || i >= kParams || !is_text(i)) return false;
  std::lock_guard<std::mutex> rl(reader_mu_);
  for (int tries = 0; tries < 8; tries++) {
    if (mu_.try_lock()) {
      std::memcpy(cache_, texts_, sizeof cache_);
      mu_.unlock();
      break;
    }
    std::this_thread::yield();  // worker holds the lock for one memcpy; otherwise keep the previous copy
  }
  std::strncpy(out, cache_[text_slot(i)], n - 1);
  out[n - 1] = 0;
  return true;
}

int Core::poll_changes(uint32_t* words, int nwords) {
  for (int w = 0; w < nwords; w++) words[w] = w < kWords ? dirty_bits_[w].exchange(0) : 0;
  return text_dirty_.exchange(false) ? 1 : 0;
}

std::string Core::state_string() const { return "rpi-audio-panel 1 onload=" + std::to_string(vals_[P_ONLOAD].load()); }

void Core::load_state(const std::string& s) {
  const char* p = std::strstr(s.c_str(), "onload=");
  if (!p) return;
  int n = std::atoi(p + 7);
  vals_[P_ONLOAD] = std::max(0, std::min(n, kPresets));
  int64_t until = clock_() + cfg_.chunk_lock_ms;
  int64_t cur = lock_until_;
  while (until > cur && !lock_until_.compare_exchange_weak(cur, until)) {}
}

void Core::mark(int i) { dirty_bits_[i >> 5].fetch_or(1u << (i & 31)); }

void Core::link_up(int64_t now) {
  link_ = Link::Connecting;
  synced_ = false;
  last_reply_ = now;
  next_status_ = now;
  status_ = Status();
  q_.clear();
  dirty_ = true;
  note("connected, waiting for status");
}

void Core::link_down(int64_t now) {
  (void)now;
  if (link_ != Link::NotFound) note("link lost");
  link_ = Link::NotFound;
  synced_ = false;
  status_ = Status();
  q_.clear();
  std::fill(hold_until_, hold_until_ + kParams, 0);
  dirty_ = true;
}

void Core::on_reply(const std::string& text, int64_t now) {
  last_reply_ = now;
  if (!text.empty() && text[0] == '{') {
    Status st;
    if (!parse_status(text, st)) { note("unreadable status reply"); return; }
    status_ = std::move(st);
    if (link_ != Link::Ok) link_ = Link::Ok;
    if (!synced_) {
      synced_ = true;
      std::fill(hold_until_, hold_until_ + kParams, 0);  // the Pi's values win after (re)connecting
      note("synced");
    }
    dirty_ = true;
  } else if (text.rfind("error", 0) == 0) {
    std::string m = text.size() > 7 ? text.substr(7) : text;
    if (!m.empty()) m[0] = static_cast<char>(toupper(static_cast<unsigned char>(m[0])));
    error_text_ = fit_text(m, kTextMax);
    error_until_ = now + cfg_.error_ms;
    note("command failed: " + text);
    dirty_ = true;
  }
}

void Core::queue(const std::string& key, const std::string& cmd, int64_t now, int param, bool debounce) {
  if (cmd.empty()) return;
  q_.push(key, cmd, debounce ? now + cfg_.debounce_ms : now, param);
}

void Core::handle_preset(int slot, int64_t now) {
  if (vals_[P_SAVE]) {
    queue("preset:save:" + std::to_string(slot), cmd_preset("save", slot), now, -1, false);
    vals_[P_SAVE] = 0;  // SAVE turns itself off
    mark(P_SAVE);
  } else {
    queue("preset:load:" + std::to_string(slot), cmd_preset("load", slot), now, -1, false);
  }
}

void Core::handle(int i, int v, int64_t now) {
  int s = strip_of(i), f = field_of(i);
  if (s < 0 || strip_id_[s].empty()) return;
  if (v == last_told_[i]) return;  // the host echoing a value we announced
  const std::string& id = strip_id_[s];
  std::string cmd, key;
  switch (f) {
    case F_IN_LEVEL: case F_OUT_LEVEL:
      v = std::max(0, std::min(v, 100));
      cmd = cmd_volume(id, f == F_OUT_LEVEL, v);
      key = "vol:" + id + (f == F_OUT_LEVEL ? ":out" : ":in");
      break;
    case F_IN_MUTE: case F_OUT_MUTE:
      v = v ? 1 : 0;
      cmd = cmd_mute(id, f == F_OUT_MUTE, v);
      key = "mute:" + id + (f == F_OUT_MUTE ? ":out" : ":in");
      break;
    case F_KIND:
      if (v < 0 || v >= kKindCustom) return;  // "Custom" is only a readback state
      cmd = cmd_name(id, v == 0 ? "" : kKindNames[v]);
      key = "name:" + id;
      if (v > 0) { name_override_[s] = kKindNames[v]; override_until_[s] = now + cfg_.hold_ms + 500; }
      break;
    default:
      return;
  }
  last_told_[i] = v;
  held_[i] = v;
  hold_until_[i] = now + cfg_.hold_ms;
  queue(key, cmd, now, i, f == F_IN_LEVEL || f == F_OUT_LEVEL);
  dirty_ = true;
}

void Core::consume(int64_t now) {
  uint32_t t[kWords];
  for (int w = 0; w < kWords; w++) t[w] = touched_[w].exchange(0);
  int taps[kPresets];
  for (int k = 0; k < kPresets; k++) taps[k] = taps_[k].exchange(0);
  // Nothing goes out before the first good status, nor while the host is still restoring the project.
  if (link_ != Link::Ok || !synced_ || now < lock_until_) return;
  for (int k = 0; k < kPresets; k++)
    if (taps[k] > 0) handle_preset(k + 1, now);
  for (int i = 0; i < kParams; i++)
    if ((t[i >> 5] >> (i & 31)) & 1u) handle(i, user_[i], now);
}

void Core::tick(int64_t now) {
  consume(now);
  if (link_ == Link::Connecting || link_ == Link::Ok) {
    if (now - last_reply_ > cfg_.reply_timeout_ms) {
      link_ = Link::NoReply;
      synced_ = false;
      q_.clear();
      dirty_ = true;
      note("no reply from rpi-audiod");
    }
  }
  if (link_ != Link::NotFound && now >= next_status_) {
    q_.push("status", cmd_status(), now, -1);
    next_status_ = now + cfg_.status_ms;
  }
  if (onload_pending_ && link_ == Link::Ok && synced_ && now >= lock_until_) {
    onload_pending_ = false;  // once per instance, not on every reconnect
    int n = vals_[P_ONLOAD];
    if (n >= 1 && n <= kPresets) queue("preset:load:" + std::to_string(n), cmd_preset("load", n), now, -1, false);
  }
  if (dirty_ || holds_active_ || (error_until_ && now >= error_until_)) {
    if (error_until_ && now >= error_until_) error_until_ = 0;
    republish(now);
  }
}

bool Core::next_command(int64_t now, std::string& out) {
  std::string key;
  int param = -1;
  if (link_ == Link::NotFound || !q_.pop(now, cfg_.min_gap_ms, out, &key, &param)) return false;
  if (param >= 0) hold_until_[param] = std::max(hold_until_[param], now + cfg_.send_hold_ms);
  if (key != "status") next_status_ = std::min(next_status_, now + 700);  // see the effect soon
  return true;
}

void Core::republish(int64_t now) {
  dirty_ = false;
  View v = make_view(link_, status_);
  if (link_ == Link::Ok && error_until_ > now) v.link = error_text_;
  holds_active_ = false;
  for (int s = 0; s < kStrips; s++) {
    strip_id_[s] = v.strip[s].identity;
    if (override_until_[s] > now) { v.strip[s].name = name_override_[s]; holds_active_ = true; }
  }

  int val[kParams] = {0};
  auto put = [&](int i, int x) { val[i] = x; };
  std::string t[kTexts];
  auto set_text = [&](int i, const std::string& s) { t[text_slot(i)] = s; };
  set_text(P_LINK, v.link);
  for (int k = 0; k < kPresets; k++) set_text(P_PRESET_NAME + k, v.preset[k]);
  for (int s = 0; s < kStrips; s++) {
    const StripView& sv = v.strip[s];
    set_text(strip_param(s, F_NAME), sv.name);
    set_text(strip_param(s, F_STATE), sv.state);
    set_text(strip_param(s, F_IN_RANGE), sv.in_range);
    set_text(strip_param(s, F_IN_NAMES), sv.in_names);
    set_text(strip_param(s, F_OUT_RANGE), sv.out_range);
    set_text(strip_param(s, F_OUT_NAMES), sv.out_names);
    put(strip_param(s, F_PRESENT), sv.present);
    put(strip_param(s, F_IN_VIS), sv.in_vis);
    put(strip_param(s, F_OUT_VIS), sv.out_vis);
    put(strip_param(s, F_IN_LEVEL), sv.in_level);
    put(strip_param(s, F_OUT_LEVEL), sv.out_level);
    put(strip_param(s, F_IN_MUTE), sv.in_mute);
    put(strip_param(s, F_OUT_MUTE), sv.out_mute);
    put(strip_param(s, F_KIND), sv.kind);
  }
  for (int i = 0; i < kParams; i++) {
    if (hold_until_[i] > now) { val[i] = held_[i]; holds_active_ = true; }
  }

  bool changed_text = false;
  {
    std::lock_guard<std::mutex> lk(mu_);
    for (int k = 0; k < kTexts; k++) {
      std::string s = fit_text(t[k], kTextMax);
      if (std::strcmp(texts_[k], s.c_str()) != 0) {
        changed_text = true;
        std::memcpy(texts_[k], s.c_str(), s.size() + 1);
      }
    }
  }
  if (changed_text) text_dirty_ = true;
  for (int i = 0; i < kParams; i++) {
    Kind k = kind_of(i);
    if (k == K_TEXT || k == K_TRIGGER || k == K_POPUP || is_local(i)) continue;
    vals_[i] = val[i];
    if (val[i] != last_told_[i]) { last_told_[i] = val[i]; mark(i); }
  }
}

}  // namespace panel
