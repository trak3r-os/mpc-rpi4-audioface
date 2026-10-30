// SPDX-License-Identifier: GPL-3.0-or-later
// Unit tests: JSON, SysEx, commands, status -> strips, debounce/hold logic, the engine over a fake MIDI link.
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdio>
#include <cstring>
#include <deque>
#include <functional>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "panel_core.h"
#include "panel_engine.h"
#include "panel_json.h"
#include "panel_layout.h"
#include "panel_model.h"
#include "panel_protocol.h"
#include "fixtures.h"
#include "params.h"  // generated: checks the layout against the parameter table the wrapper uses

using namespace panel;

static int g_fail = 0, g_checks = 0;
#define CHECK(c)                                                                  \
  do {                                                                            \
    g_checks++;                                                                   \
    if (!(c)) { g_fail++; std::printf("FAIL %s:%d: %s\n", __FILE__, __LINE__, #c); } \
  } while (0)
#define CHECK_EQ(a, b)                                                                                    \
  do {                                                                                                    \
    g_checks++;                                                                                           \
    auto va = (a); auto vb = (b);                                                                         \
    if (!(va == vb)) { g_fail++; std::printf("FAIL %s:%d: %s == %s\n", __FILE__, __LINE__, #a, #b); }     \
  } while (0)

// ---- JSON ------------------------------------------------------------------------------------------

static void test_json() {
  Json j;
  CHECK(parse_json("{\"a\":1,\"b\":[true,false,null,\"x\\n\\u0041\\u00e9\"],\"c\":{\"d\":-2.5e1}}", j));
  CHECK_EQ(j.get("a")->as_int(0), 1);
  CHECK_EQ(j.get("b")->arr.size(), size_t(4));
  CHECK(j.get("b")->arr[0].as_bool(false));
  CHECK_EQ(j.get("b")->arr[3].str, std::string("x\nA?"));
  CHECK_EQ(j.get("c")->get("d")->as_int(0), -25);
  CHECK(j.get("zzz") == nullptr);
  CHECK(parse_json("  [ ]  ", j));
  CHECK(!parse_json("{\"a\":1,}", j));
  CHECK(!parse_json("{\"a\":1} x", j));
  CHECK(!parse_json("{\"a\":", j));
  CHECK(!parse_json("[1,2", j));
  CHECK(!parse_json("\"unterminated", j));
  CHECK(!parse_json("{\"a\":\"\\q\"}", j));
  CHECK(!parse_json("", j));
  CHECK(!parse_json(std::string(40, '[') + std::string(40, ']'), j));  // depth limit
  CHECK(parse_json(std::string(10, '[') + std::string(10, ']'), j));
}

// ---- SysEx and commands ----------------------------------------------------------------------------

static void test_protocol() {
  auto m = encode_command("status");
  CHECK_EQ(m.size(), size_t(11));
  CHECK(m[0] == 0xF0 && m[1] == 0x7D && m[2] == 0x52 && m[3] == 0x41 && m.back() == 0xF7);
  CHECK(encode_command("").empty());
  CHECK(encode_command("caf\xc3\xa9").empty());
  CHECK(encode_command(std::string(300, 'a')).empty());
  CHECK(!encode_command(std::string(195, 'a')).empty());
  CHECK(encode_command(std::string(196, 'a')).empty());

  auto frame = [](const std::string& t, uint8_t kind) {
    std::vector<uint8_t> v = {0xF0, 0x7D, 0x52, kind};
    v.insert(v.end(), t.begin(), t.end());
    v.push_back(0xF7);
    return v;
  };
  std::string out;
  SysexAssembler a;
  auto whole = frame("ok rpi-audio", 0x42);
  CHECK(a.feed(whole.data(), whole.size(), out));
  CHECK_EQ(out, std::string("ok rpi-audio"));

  // split across three events, as the sequencer may do
  std::string long_text(500, 'x');
  long_text[0] = '{';
  auto big = frame(long_text, 0x42);
  CHECK(!a.feed(big.data(), 100, out));
  CHECK(!a.feed(big.data() + 100, 200, out));
  CHECK(a.feed(big.data() + 300, big.size() - 300, out));
  CHECK_EQ(out, long_text);

  // an echo of our own command (RA), a non-SysEx byte, bytes without a start, and a restart
  auto echo = frame("status", 0x41);
  CHECK(!a.feed(echo.data(), echo.size(), out));
  uint8_t junk[] = {0x90, 0x40, 0x7F};
  CHECK(!a.feed(junk, 3, out));
  uint8_t tail[] = {'o', 'k', 0xF7};
  CHECK(!a.feed(tail, 3, out));  // no F0 seen
  CHECK(!a.feed(big.data(), 50, out));
  auto next = frame("ok", 0x42);
  CHECK(a.feed(next.data(), next.size(), out));  // a new F0 restarts the message
  CHECK_EQ(out, std::string("ok"));
  uint8_t bad[] = {0xF0, 0x7D, 0x52, 0x42, 'a', 0x90, 'b', 0xF7};
  CHECK(!a.feed(bad, sizeof bad, out));  // a status byte inside aborts it

  CHECK_EQ(cmd_status(), std::string("status"));
  CHECK_EQ(cmd_mute("usb-1:2-X", false, true), std::string("mute usb-1:2-X in on"));
  CHECK_EQ(cmd_mute("usb-1:2-X", true, false), std::string("mute usb-1:2-X out off"));
  CHECK_EQ(cmd_volume("usb-1:2-X", true, 73), std::string("volume usb-1:2-X out 73"));
  CHECK_EQ(cmd_volume("usb-1:2-X", false, 250), std::string("volume usb-1:2-X in 100"));
  CHECK_EQ(cmd_volume("usb-1:2-X", false, -4), std::string("volume usb-1:2-X in 0"));
  CHECK_EQ(cmd_name("id", "Drum machine"), std::string("name id Drum machine"));
  CHECK_EQ(cmd_name("id", ""), std::string("name id"));
  CHECK_EQ(cmd_name("id", std::string(40, 'z')).size(), std::string("name id ").size() + 24);
  CHECK_EQ(cmd_preset("save", 3), std::string("preset save 3"));
  CHECK(cmd_preset("save", 9).empty());
  CHECK(cmd_preset("wipe", 1).empty());
  CHECK(cmd_mute("bad id", false, true).empty());
  CHECK(cmd_volume("", false, 5).empty());
  CHECK_EQ(fit_text("abcdefghijklmnopqrstuvwxyz", 23), std::string("abcdefghijklmnopqrst..."));
  CHECK_EQ(fit_text("caf\xc3\xa9", 23), std::string("caf??"));
}

// ---- status -> strips ------------------------------------------------------------------------------

static void test_model() {
  Status st;
  CHECK(parse_status(three_devices(), st));
  CHECK_EQ(st.devices.size(), size_t(3));
  CHECK_EQ(st.gadget_channels, 26);
  CHECK(st.devices[1].in.level == -1);  // JSON null
  CHECK(st.preset_saved[0] && !st.preset_saved[1] && st.preset_saved[2]);
  CHECK(!parse_status("[1]", st));
  CHECK(!parse_status("nope", st));

  View v = make_view(Link::Ok, st);
  CHECK_EQ(v.link, std::string("44.1 kHz | 26x26"));
  CHECK_EQ(v.preset[0], std::string("Live"));
  CHECK_EQ(v.preset[1], std::string("-"));
  CHECK_EQ(v.preset[2], std::string("Preset 3"));  // saved without a name
  CHECK(v.strip[0].present && v.strip[1].present && v.strip[2].present && !v.strip[3].present);
  CHECK_EQ(v.strip[0].name, std::string("Mixer"));
  CHECK_EQ(v.strip[0].in_range, std::string("IN 1-2"));
  CHECK_EQ(v.strip[0].out_range, std::string("OUT 3-4"));
  CHECK_EQ(v.strip[0].in_names, std::string("Main L, Main R"));
  CHECK_EQ(v.strip[0].kind, 10);  // "Mixer" is a picker entry
  CHECK_EQ(v.strip[1].name, std::string("Valeton GP-150"));
  CHECK_EQ(v.strip[1].in_range, std::string("IN 3-8"));
  CHECK_EQ(v.strip[1].in_names, std::string("Out L, Out R"));  // empty names dropped
  CHECK_EQ(v.strip[1].in_level, 100);                           // unknown level -> 100
  CHECK_EQ(v.strip[1].in_mute, 1);
  CHECK_EQ(v.strip[1].kind, kKindCustom);
  CHECK_EQ(v.strip[2].in_range, std::string("IN 9-20"));
  CHECK_EQ(v.strip[2].out_range, std::string("OUT 9-10"));
  CHECK_EQ(v.strip[2].kind, 13);
  CHECK_EQ(v.strip[0].state, std::string("running"));
  CHECK_EQ(v.strip[0].in_vis, 1);
  CHECK_EQ(v.strip[0].out_level, 80);
  CHECK_EQ(v.strip[3].in_vis, 0);

  // ordering: by IN start, then OUT start; OUT-only after IN devices; parked last
  Status o;
  CHECK(parse_status(status_json({device_json("usb-zzzz:1-A", "OutOnly", "", dir_json(1, 2, true, false, "50")),
                                  device_json("usb-bbbb:1-B", "Second", dir_json(5, 2, true, false, "50"), ""),
                                  device_json("usb-cccc:1-C", "Parked", dir_json(-1, 2, false, false, "50"), ""),
                                  device_json("usb-dddd:1-D", "First", dir_json(1, 2, true, false, "50"), "")}),
                   o));
  auto order = order_devices(o);
  CHECK_EQ(order[0]->name, std::string("First"));
  CHECK_EQ(order[1]->name, std::string("Second"));
  CHECK_EQ(order[2]->name, std::string("OutOnly"));
  CHECK_EQ(order[3]->name, std::string("Parked"));
  View ov = make_view(Link::Ok, o);
  CHECK_EQ(ov.strip[2].in_vis, 2);   // device present, no IN direction: dimmed
  CHECK_EQ(ov.strip[2].in_range, std::string("-"));
  CHECK_EQ(ov.strip[3].state, std::string("parked"));
  CHECK_EQ(ov.strip[3].in_range, std::string("-"));

  // states
  Status b;
  CHECK(parse_status(status_json({device_json("usb-1111:1-A", "", dir_json(2, 2, false, false, "1", "", "USB budget"), ""),
                                  device_json("usb-2222:1-B", "", dir_json(4, 2, false, false, "1"), "")}),
                   b));
  View bv = make_view(Link::Ok, b);
  CHECK_EQ(bv.strip[0].state, std::string("waiting: USB budget"));
  CHECK_EQ(bv.strip[1].state, std::string("not running"));
  CHECK_EQ(bv.strip[0].name, std::string("usb-"));  // no name: the card
  CHECK_EQ(bv.strip[0].kind, 0);                      // no custom name: Default

  // more than six devices, link states, long names
  std::vector<std::string> many;
  for (int i = 0; i < 8; i++)
    many.push_back(device_json("usb-" + std::to_string(1000 + i) + ":1-X", "Dev" + std::to_string(i),
                               dir_json(1 + i, 1, true, false, "10"), ""));
  Status m8;
  CHECK(parse_status(status_json(many), m8));
  CHECK_EQ(make_view(Link::Ok, m8).link, std::string("44.1 kHz | 26x26 | +2"));
  CHECK_EQ(make_view(Link::Ok, m8).strip[0].in_range, std::string("IN 1"));  // one channel
  CHECK_EQ(link_text(Link::NotFound, m8), std::string("Pi not found"));
  CHECK_EQ(link_text(Link::NoReply, m8), std::string("No reply"));
  Status n;
  CHECK(parse_status(status_json({device_json("usb-1:1-A", std::string(40, 'N'), dir_json(1, 2, true, false, "5"), "")}), n));
  CHECK_EQ(make_view(Link::Ok, n).strip[0].name.size(), size_t(kTextMax));
  Status idle;
  CHECK(parse_status("{\"host_playback_rate\":0,\"devices\":[]}", idle));
  CHECK_EQ(link_text(Link::Ok, idle), std::string("idle"));
}

// ---- layout vs generated params.h ------------------------------------------------------------------

static void test_layout() {
  CHECK_EQ(NPARAMS, kParams);
  char b[48];
  for (int i = 0; i < kParams; i++) {
    CHECK_EQ(std::string(PARAMS[i].key), std::string(key_name(i, b, sizeof b)));
    CHECK_EQ(PARAMS[i].string_display != 0, is_text(i));
    CHECK_EQ(PARAMS[i].momentary != 0, kind_of(i) == K_TRIGGER);
    CHECK_EQ(PARAMS[i].popup_of >= 0, kind_of(i) == K_POPUP);
    if (kind_of(i) == K_KIND) CHECK_EQ(PARAMS[i].nopts, kKindCount);
    if (kind_of(i) == K_MUTE) CHECK_EQ(PARAMS[i].nopts, 2);
    if (kind_of(i) == K_LEVEL) { CHECK(PARAMS[i].max == 100 && PARAMS[i].min == 0); CHECK(PARAMS[i].int_display); }
  }
  CHECK_EQ(PARAMS[P_ONLOAD].nopts, kPresets + 1);
  for (int i = 0; i < kKindCount; i++) CHECK_EQ(std::string(PARAMS[strip_param(0, F_KIND)].opts[i]), std::string(kKindNames[i]));
  CHECK_EQ(PARAMS[strip_param(0, F_IN_VIS)].nopts, 3);
  CHECK_EQ(key_index("s3_out_mute"), strip_param(2, F_OUT_MUTE));
  CHECK_EQ(key_index("nope"), -1);
  int texts = 0;
  for (int i = 0; i < kParams; i++) if (is_text(i)) { CHECK_EQ(text_slot(i), texts); texts++; }
  CHECK_EQ(texts, kTexts);
  CHECK(PARAMS[P_LINK].max == 1 && NPARAMS == 109);
}

// ---- command queue ---------------------------------------------------------------------------------

static void test_queue() {
  CommandQueue q;
  std::string c, k;
  int p;
  q.push("a", "A1", 100, 1);
  q.push("a", "A2", 150, 1);  // replaces, keeps the earlier due time
  CHECK_EQ(q.size(), size_t(1));
  CHECK(!q.pop(99, 100, c, &k, &p));
  CHECK(q.pop(100, 100, c, &k, &p));
  CHECK_EQ(c, std::string("A2"));
  q.push("b", "B", 0, -1);
  q.push("c", "C", 0, -1);
  CHECK(!q.pop(150, 100, c, &k, &p));  // min gap since the last send
  CHECK(q.pop(200, 100, c, &k, &p) && c == "B");
  CHECK(!q.pop(250, 100, c, &k, &p));
  CHECK(q.pop(300, 100, c, &k, &p) && c == "C");
  CHECK(!q.pop(1000, 100, c, &k, &p));
}

// ---- core logic with a fake clock ------------------------------------------------------------------

struct Sim {
  int64_t t = 1000;
  std::vector<std::string> sent, logs;
  bool auto_reply = true;  // the Pi answers every status request with `status`
  std::string status = three_devices();
  Core core;
  explicit Sim(CoreConfig cfg = {})
      : core(cfg, [this](const std::string& m) { logs.push_back(m); }, [this] { return t; }) {
    core.begin(t);
  }
  void advance(int ms, bool pump = true) {
    for (int i = 0; i < ms; i += 10) {
      t += 10;
      core.tick(t);
      std::string c;
      while (pump && core.next_command(t, c)) {
        sent.push_back(c);
        if (auto_reply && c == "status") core.on_reply(status, t);
      }
    }
  }
  void connect(const std::string& json) {
    core.link_up(t);
    advance(20);
    core.on_reply(json, t);
    advance(20);
  }
  int count(const std::string& prefix) const {
    int n = 0;
    for (const auto& s : sent) n += s.rfind(prefix, 0) == 0;
    return n;
  }
};

static int idx(int s, int f) { return strip_param(s, f); }

static void test_core_sync_and_holds() {
  Sim sim;
  sim.auto_reply = false;
  // Host restores values before we are connected: local only, nothing is sent.
  sim.core.set_param(idx(0, F_IN_LEVEL), 33);
  sim.core.set_param(idx(0, F_IN_MUTE), 1);
  sim.advance(500);
  CHECK(sim.sent.empty());
  CHECK_EQ(sim.core.get_value(idx(0, F_PRESENT)), 0);
  sim.core.set_param(P_SAVE, 1);  // within the startup lock: not a restore value we keep
  CHECK_EQ(sim.core.get_value(P_SAVE), 0);

  sim.core.link_up(sim.t);
  sim.advance(50);
  CHECK_EQ(sim.count("status"), 1);  // the first status request goes out right away
  sim.core.set_param(idx(0, F_IN_LEVEL), 44);  // connected, not yet synced
  sim.advance(100);
  CHECK_EQ(sim.count("volume"), 0);
  char txt[32];
  sim.core.get_text(P_LINK, txt, sizeof txt);
  CHECK_EQ(std::string(txt), std::string("Connecting..."));

  sim.core.on_reply(three_devices(), sim.t);
  sim.advance(30);
  CHECK(sim.core.synced());
  sim.core.get_text(P_LINK, txt, sizeof txt);
  CHECK_EQ(std::string(txt), std::string("44.1 kHz | 26x26"));
  CHECK_EQ(sim.core.get_value(idx(0, F_PRESENT)), 1);
  CHECK_EQ(sim.core.get_value(idx(0, F_IN_LEVEL)), 100);  // the Pi's value, not the restored 33/44
  CHECK_EQ(sim.core.get_value(idx(0, F_OUT_LEVEL)), 80);
  CHECK_EQ(sim.core.get_value(idx(1, F_IN_MUTE)), 1);
  CHECK_EQ(sim.count("volume") + sim.count("mute"), 0);
  uint32_t w[kWords];
  int text = sim.core.poll_changes(w, kWords);
  CHECK(text == 1);
  CHECK((w[idx(0, F_PRESENT) >> 5] >> (idx(0, F_PRESENT) & 31)) & 1u);
  CHECK(sim.core.poll_changes(w, kWords) == 0);  // announced once
  bool any = false;
  for (int i = 0; i < kWords; i++) any |= w[i] != 0;
  CHECK(!any);

  // Still inside the startup lock (3 s): user changes are ignored.
  sim.core.set_param(idx(0, F_IN_LEVEL), 10);
  sim.advance(200);
  CHECK_EQ(sim.count("volume"), 0);
  sim.advance(3000);

  // A level change: sent once debounced, held against stale statuses, then the Pi's value wins again.
  std::string base = three_devices();
  sim.sent.clear();
  sim.core.set_param(idx(0, F_IN_LEVEL), 55);
  sim.advance(50);
  CHECK_EQ(sim.count("volume"), 0);  // debounce
  sim.core.set_param(idx(0, F_IN_LEVEL), 58);
  sim.advance(100);
  CHECK_EQ(sim.count("volume"), 1);
  bool found = false;
  for (auto& s : sim.sent) found |= s == "volume usb-aaaa:0001-MIX in 58";
  CHECK(found);
  sim.core.on_reply(base, sim.t);  // stale status still says 100
  sim.advance(30);
  CHECK_EQ(sim.core.get_value(idx(0, F_IN_LEVEL)), 58);  // held
  sim.advance(2200);
  sim.core.on_reply(base, sim.t);  // the Pi never applied it
  sim.advance(30);
  CHECK_EQ(sim.core.get_value(idx(0, F_IN_LEVEL)), 100);
  sim.core.poll_changes(w, kWords);
  CHECK((w[idx(0, F_IN_LEVEL) >> 5] >> (idx(0, F_IN_LEVEL) & 31)) & 1u);  // the host is told it came back

  // An echo of a value we announced is not a user action.
  sim.sent.clear();
  sim.core.poll_changes(w, kWords);
  std::string changed = base;
  size_t pos = changed.find("\"level\":80");
  changed.replace(pos, 10, "\"level\":60");
  sim.core.on_reply(changed, sim.t);
  sim.advance(30);
  CHECK_EQ(sim.core.get_value(idx(0, F_OUT_LEVEL)), 60);
  sim.core.poll_changes(w, kWords);
  CHECK((w[idx(0, F_OUT_LEVEL) >> 5] >> (idx(0, F_OUT_LEVEL) & 31)) & 1u);
}

static void test_core_commands() {
  CoreConfig cfg;
  Sim sim(cfg);
  sim.advance(3100);
  sim.connect(three_devices());
  sim.sent.clear();

  // mute, name, preset: immediate, rate limited to 10/s
  sim.core.set_param(idx(2, F_OUT_MUTE), 1);
  sim.advance(110);
  bool m = false;
  for (auto& s : sim.sent) m |= s == "mute usb-cccc:0003-TRK out on";
  CHECK(m);
  sim.sent.clear();
  sim.core.set_param(idx(1, F_KIND), 1);  // Guitar
  sim.advance(110);
  bool n = false;
  for (auto& s : sim.sent) n |= s == "name usb-84ef:0186-GP Guitar";
  CHECK(n);
  char txt[32];
  sim.core.get_text(idx(1, F_NAME), txt, sizeof txt);
  CHECK_EQ(std::string(txt), std::string("Guitar"));  // shown at once, until the Pi confirms
  sim.sent.clear();
  sim.core.set_param(idx(1, F_KIND), 0);  // Default clears
  sim.advance(110);
  bool c = false;
  for (auto& s : sim.sent) c |= s == "name usb-84ef:0186-GP";
  CHECK(c);
  sim.sent.clear();
  sim.core.set_param(idx(1, F_KIND), kKindCustom);  // readback state only
  sim.advance(300);
  CHECK_EQ(sim.count("name"), 0);

  // 20 toggles on 5 controls in 100 ms: never more than 10 commands per second
  sim.advance(3000);
  sim.sent.clear();
  for (int rep = 0; rep < 3; rep++) {
    for (int s = 0; s < 3; s++) {
      sim.core.set_param(idx(s, F_IN_MUTE), (rep & 1) ? 0 : 1);
      sim.core.set_param(idx(s, F_OUT_MUTE), (rep & 1) ? 0 : 1);
    }
  }
  sim.advance(1000);
  int sent_total = static_cast<int>(sim.sent.size());
  CHECK(sent_total <= 11);  // 10 per second plus the boundary
  CHECK(sent_total >= 5);  // five controls end up different from the Pi's value

  // presets: SAVE arms the next tap
  sim.advance(4000);
  sim.sent.clear();
  sim.core.set_param(P_PRESET + 1, 1);  // tap preset 2 -> load
  sim.advance(110);
  CHECK_EQ(sim.count("preset load 2"), 1);
  sim.core.set_param(P_SAVE, 1);
  CHECK_EQ(sim.core.get_value(P_SAVE), 1);
  sim.core.set_param(P_PRESET + 2, 1);  // tap preset 3 -> save, SAVE turns off
  sim.advance(210);
  CHECK_EQ(sim.count("preset save 3"), 1);
  CHECK_EQ(sim.core.get_value(P_SAVE), 0);
  uint32_t w[kWords];
  sim.core.poll_changes(w, kWords);
  sim.core.set_param(P_PRESET + 3, 1);
  sim.advance(110);
  CHECK_EQ(sim.count("preset load 4"), 1);

  // a command error shows in the link readout for a while
  sim.core.on_reply("error: preset 4 is empty", sim.t);
  sim.advance(20);
  sim.core.get_text(P_LINK, txt, sizeof txt);
  CHECK_EQ(std::string(txt), std::string("Preset 4 is empty"));
  sim.advance(4200);
  sim.core.get_text(P_LINK, txt, sizeof txt);
  CHECK_EQ(std::string(txt), std::string("44.1 kHz | 26x26"));

  // an absent strip has no identity: no command
  sim.sent.clear();
  sim.core.set_param(idx(4, F_IN_MUTE), 1);
  sim.advance(300);
  CHECK_EQ(sim.count("mute"), 0);
}

static void test_core_link() {
  Sim sim;
  sim.advance(3100);
  sim.connect(three_devices());
  CHECK(sim.core.synced());
  // the Pi stops answering
  sim.auto_reply = false;
  sim.advance(4500);
  CHECK(sim.core.link() == Link::NoReply);
  CHECK(!sim.core.synced());
  char txt[32];
  sim.core.get_text(P_LINK, txt, sizeof txt);
  CHECK_EQ(std::string(txt), std::string("No reply"));
  sim.sent.clear();
  sim.core.set_param(idx(0, F_IN_MUTE), 1);  // not synced: nothing is sent
  sim.advance(300);
  CHECK_EQ(sim.count("mute"), 0);
  // it answers again: the Pi's values replace whatever the UI held
  sim.core.on_reply(three_devices(), sim.t);
  sim.advance(30);
  CHECK(sim.core.link() == Link::Ok && sim.core.synced());
  CHECK_EQ(sim.core.get_value(idx(0, F_IN_MUTE)), 0);
  // the cable is pulled
  sim.core.link_down(sim.t);
  sim.advance(30);
  sim.core.get_text(P_LINK, txt, sizeof txt);
  CHECK_EQ(std::string(txt), std::string("Pi not found"));
  CHECK_EQ(sim.core.get_value(idx(0, F_PRESENT)), 0);
  sim.sent.clear();
  sim.advance(2000);
  CHECK(sim.sent.empty());  // no polling while the Pi is away
}

static void test_core_onload() {
  Sim sim;
  sim.core.load_state("rpi-audio-panel 1 onload=2");  // project restore
  CHECK_EQ(sim.core.get_value(P_ONLOAD), 2);
  CHECK(sim.core.state_string().find("onload=2") != std::string::npos);
  sim.connect(three_devices());
  sim.advance(2000);
  CHECK_EQ(sim.count("preset load"), 0);  // inside the startup lock
  sim.advance(2500);
  CHECK_EQ(sim.count("preset load 2"), 1);
  // after a reconnect it is not sent again
  sim.core.link_down(sim.t);
  sim.connect(three_devices());
  sim.advance(5000);
  CHECK_EQ(sim.count("preset load"), 1);
  sim.core.load_state("onload=99");
  CHECK_EQ(sim.core.get_value(P_ONLOAD), kPresets);

  Sim none;
  none.connect(three_devices());
  none.advance(6000);
  CHECK_EQ(none.count("preset load"), 0);  // None
}

static void test_core_text() {
  Sim sim;
  sim.advance(3100);
  sim.connect(three_devices());
  char txt[32];
  sim.core.get_text(idx(1, F_NAME), txt, sizeof txt);
  CHECK_EQ(std::string(txt), std::string("Valeton GP-150"));
  sim.core.get_text(idx(1, F_IN_RANGE), txt, sizeof txt);
  CHECK_EQ(std::string(txt), std::string("IN 3-8"));
  sim.core.get_text(P_PRESET_NAME, txt, sizeof txt);
  CHECK_EQ(std::string(txt), std::string("Live"));
  CHECK(!sim.core.get_text(idx(0, F_IN_LEVEL), txt, sizeof txt));  // not a text parameter
  char tiny[4];
  sim.core.get_text(P_LINK, tiny, sizeof tiny);
  CHECK_EQ(std::strlen(tiny), size_t(3));
}

// ---- engine over a fake MIDI link ------------------------------------------------------------------

static bool wait_for(const std::function<bool()>& f, int ms = 4000) {
  for (int i = 0; i < ms / 5; i++) {
    if (f()) return true;
    std::this_thread::sleep_for(std::chrono::milliseconds(5));
  }
  return f();
}

static void test_engine() {
  CoreConfig cfg;
  cfg.retry_ms = 40;
  cfg.status_ms = 60;
  cfg.min_gap_ms = 10;
  cfg.debounce_ms = 20;
  cfg.hold_ms = 150;
  cfg.send_hold_ms = 200;
  cfg.startup_lock_ms = 150;
  cfg.reply_timeout_ms = 400;
  auto io = std::unique_ptr<FakeIo>(new FakeIo);
  FakeIo* fake = io.get();
  std::vector<std::string> logs;
  std::mutex lm;
  {
    Engine eng(std::move(io), cfg, [&](const std::string& m) { std::lock_guard<std::mutex> lk(lm); logs.push_back(m); });
    Core& c = eng.core();
    char txt[32];
    CHECK(wait_for([&] { return fake->connects > 2; }));  // keeps looking while the Pi is away
    c.get_text(P_LINK, txt, sizeof txt);
    CHECK_EQ(std::string(txt), std::string("Pi not found"));
    CHECK_EQ(fake->count("status"), 0);

    fake->present = true;
    CHECK(wait_for([&] { return c.synced(); }));  // status reassembled from 90-byte pieces
    c.get_text(P_LINK, txt, sizeof txt);
    CHECK_EQ(std::string(txt), std::string("44.1 kHz | 26x26"));
    CHECK_EQ(c.get_value(strip_param(2, F_PRESENT)), 1);
    c.get_text(strip_param(0, F_NAME), txt, sizeof txt);
    CHECK_EQ(std::string(txt), std::string("Mixer"));

    std::this_thread::sleep_for(std::chrono::milliseconds(200));  // past the startup lock
    // a burst of drags, from another thread, while the engine polls
    std::atomic<bool> stop{false};
    std::thread reader([&] {
      uint32_t w[kWords];
      char b[32];
      while (!stop) {
        for (int i = 0; i < kParams; i++) { c.get_value(i); if (is_text(i)) c.get_text(i, b, sizeof b); }
        c.poll_changes(w, kWords);
      }
    });
    for (int v = 0; v <= 100; v += 2) {
      c.set_param(strip_param(0, F_IN_LEVEL), v);
      std::this_thread::sleep_for(std::chrono::milliseconds(2));
    }
    CHECK(wait_for([&] { return fake->count("volume usb-aaaa:0001-MIX in 100") == 1; }));
    CHECK(fake->count("volume usb-aaaa:0001-MIX in 100") == 1);
    stop = true;
    reader.join();
    {
      std::lock_guard<std::mutex> lk(fake->mu);
      int volumes = 0;
      for (auto& s : fake->sent) volumes += s.rfind("volume", 0) == 0;
      CHECK(volumes >= 1 && volumes < 40);  // debounced, not one per step
    }

    // the Pi goes away: the engine notices, shows it, and syncs again when it returns
    fake->present = false;
    CHECK(wait_for([&] { c.get_text(P_LINK, txt, sizeof txt); return std::string(txt) == "Pi not found"; }));
    CHECK(!c.synced());
    fake->present = true;
    CHECK(wait_for([&] { return c.synced(); }));
  }  // destructor joins the thread
}

static void test_conf() {
  Conf d = parse_conf("");
  CHECK_EQ(d.client, std::string("rpi-audio"));
  CHECK_EQ(d.port, std::string("rpi-audio MIDI 1"));
  Conf c = parse_conf("# comment\nclient = My Pi  # trailing\n port=Control 2\nbogus\nunknown = 1\nclient =\n");
  CHECK_EQ(c.client, std::string("My Pi"));
  CHECK_EQ(c.port, std::string("Control 2"));
}

int main() {
  test_conf();
  test_json();
  test_protocol();
  test_model();
  test_layout();
  test_queue();
  test_core_sync_and_holds();
  test_core_commands();
  test_core_link();
  test_core_onload();
  test_core_text();
  test_engine();
  std::printf("%d checks, %d failed\n", g_checks, g_fail);
  return g_fail ? 1 : 0;
}
