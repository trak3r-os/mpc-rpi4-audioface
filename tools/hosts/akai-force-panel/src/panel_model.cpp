// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_model.h"

#include <algorithm>
#include <cstdio>
#include <strings.h>

#include "panel_json.h"
#include "panel_protocol.h"

namespace panel {
namespace {

DirStatus parse_dir(const Json& j) {
  DirStatus d;
  if (j.type != Json::Obj) return d;
  d.present = true;
  if (const Json* v = j.get("channels")) d.channels = v->as_int(0);
  if (const Json* v = j.get("start")) d.start = v->as_int(-1);
  if (const Json* v = j.get("running")) d.running = v->as_bool(false);
  if (const Json* v = j.get("muted")) d.muted = v->as_bool(false);
  if (const Json* v = j.get("level")) d.level = v->as_int(-1);
  if (const Json* v = j.get("blocked")) d.blocked = v->type == Json::Str ? !v->str.empty() : v->as_bool(true);
  if (const Json* v = j.get("names"))
    if (v->type == Json::Arr)
      for (const Json& n : v->arr) d.names.push_back(n.as_str());
  return d;
}

constexpr int kFar = 1 << 20;
int key_of(const DirStatus& d) { return d.present && d.start >= 0 ? d.start : kFar; }

std::string range_text(const DirStatus& d, const char* tag) {
  if (!d.present || d.start < 0 || d.channels < 1) return "-";
  char b[32];
  if (d.channels == 1) std::snprintf(b, sizeof b, "%s %d", tag, d.start);
  else std::snprintf(b, sizeof b, "%s %d-%d", tag, d.start, d.start + d.channels - 1);
  return b;
}

std::string names_text(const DirStatus& d) {
  std::string out;
  for (size_t i = 0; i < d.names.size() && static_cast<int>(i) < std::max(d.channels, 0); i++) {
    if (d.names[i].empty()) continue;
    if (!out.empty()) out += ", ";
    out += d.names[i];
  }
  return fit_text(out, kTextMax);
}

std::string state_text(const DeviceStatus& dev) {
  const DirStatus* dirs[2] = {&dev.in, &dev.out};
  bool parked = false, blocked = false, stopped = false;
  for (const DirStatus* d : dirs) {
    if (!d->present) continue;
    if (d->start < 0) parked = true;
    else if (d->blocked) blocked = true;
    else if (!d->running) stopped = true;
  }
  if (parked) return "parked";
  if (blocked) return "waiting: USB budget";
  if (stopped) return "not running";
  return "running";
}

int kind_of_name(const std::string& n) {
  if (n.empty()) return 0;
  for (int i = 1; i < kKindCustom; i++)
    if (!strcasecmp(n.c_str(), kKindNames[i])) return i;
  return kKindCustom;
}

}  // namespace

bool parse_status(const std::string& text, Status& out) {
  Json j;
  if (!parse_json(text, j) || j.type != Json::Obj) return false;
  Status s;
  if (const Json* v = j.get("host_playback_rate")) s.playback_rate = v->as_int(0);
  if (const Json* v = j.get("host_capture_rate")) s.capture_rate = v->as_int(0);
  if (const Json* v = j.get("gadget_channels")) s.gadget_channels = v->as_int(0);
  if (const Json* devs = j.get("devices"))
    if (devs->type == Json::Arr)
      for (const Json& d : devs->arr) {
        if (d.type != Json::Obj) continue;
        DeviceStatus dev;
        if (const Json* v = d.get("identity")) dev.identity = v->as_str();
        if (const Json* v = d.get("card")) dev.card = v->as_str();
        if (const Json* v = d.get("name")) dev.name = v->as_str();
        if (const Json* v = d.get("in")) dev.in = parse_dir(*v);
        if (const Json* v = d.get("out")) dev.out = parse_dir(*v);
        if (dev.identity.empty()) continue;  // nothing to address a command to
        s.devices.push_back(std::move(dev));
      }
  if (const Json* ps = j.get("presets"))
    if (ps->type == Json::Arr)
      for (const Json& p : ps->arr) {
        const Json* slot = p.get("slot");
        int n = slot ? slot->as_int(0) : 0;
        if (n < 1 || n > kPresets) continue;
        s.preset_saved[n - 1] = true;
        if (const Json* v = p.get("name")) s.preset_name[n - 1] = v->as_str();
      }
  out = std::move(s);
  return true;
}

std::vector<const DeviceStatus*> order_devices(const Status& s) {
  std::vector<const DeviceStatus*> v;
  for (const DeviceStatus& d : s.devices) v.push_back(&d);
  std::stable_sort(v.begin(), v.end(), [](const DeviceStatus* a, const DeviceStatus* b) {
    if (key_of(a->in) != key_of(b->in)) return key_of(a->in) < key_of(b->in);
    if (key_of(a->out) != key_of(b->out)) return key_of(a->out) < key_of(b->out);
    return a->identity < b->identity;
  });
  return v;
}

std::string link_text(Link link, const Status& s) {
  switch (link) {
    case Link::NotFound: return "Pi not found";
    case Link::Connecting: return "Connecting...";
    case Link::NoReply: return "No reply";
    case Link::Ok: break;
  }
  char b[64];
  if (s.playback_rate > 0) std::snprintf(b, sizeof b, "%g kHz", s.playback_rate / 1000.0);
  else std::snprintf(b, sizeof b, "idle");
  std::string t = b;
  if (s.gadget_channels > 0) t += " | " + std::to_string(s.gadget_channels) + "x" + std::to_string(s.gadget_channels);
  if (s.devices.size() > static_cast<size_t>(kStrips)) t += " | +" + std::to_string(s.devices.size() - kStrips);
  return fit_text(t, kTextMax);
}

View make_view(Link link, const Status& s) {
  View v;
  v.link = link_text(link, s);
  for (int k = 0; k < kPresets; k++)
    v.preset[k] = !s.preset_saved[k] ? "-"
                  : s.preset_name[k].empty() ? "Preset " + std::to_string(k + 1)
                                             : fit_text(s.preset_name[k], kTextMax);
  std::vector<const DeviceStatus*> devs = order_devices(s);
  for (int i = 0; i < kStrips && i < static_cast<int>(devs.size()); i++) {
    const DeviceStatus& d = *devs[i];
    StripView& sv = v.strip[i];
    sv.present = true;
    sv.identity = d.identity;
    sv.name = fit_text(!d.name.empty() ? d.name : !d.card.empty() ? d.card : d.identity, kTextMax);
    sv.state = state_text(d);
    sv.in_vis = d.in.present ? 1 : 2;
    sv.out_vis = d.out.present ? 1 : 2;
    sv.in_range = range_text(d.in, "IN");
    sv.out_range = range_text(d.out, "OUT");
    sv.in_names = names_text(d.in);
    sv.out_names = names_text(d.out);
    sv.in_level = d.in.level >= 0 ? std::min(d.in.level, 100) : 100;
    sv.out_level = d.out.level >= 0 ? std::min(d.out.level, 100) : 100;
    sv.in_mute = d.in.muted;
    sv.out_mute = d.out.muted;
    sv.kind = kind_of_name(d.name);
  }
  return v;
}

}  // namespace panel
