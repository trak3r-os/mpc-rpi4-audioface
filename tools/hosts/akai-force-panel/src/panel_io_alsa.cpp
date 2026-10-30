// SPDX-License-Identifier: GPL-3.0-or-later
#include <cstdio>
#include <cstring>
#include <deque>
#include <fstream>
#include <sstream>

#include "panel_io.h"

#ifndef PANEL_NO_ALSA
#include <alsa/asoundlib.h>
#include <poll.h>
#endif

namespace panel {

Conf parse_conf(const std::string& text) {
  Conf c;
  std::istringstream in(text);
  std::string line;
  auto trim = [](std::string s) {
    size_t a = s.find_first_not_of(" \t\r"), b = s.find_last_not_of(" \t\r");
    return a == std::string::npos ? std::string() : s.substr(a, b - a + 1);
  };
  while (std::getline(in, line)) {
    size_t h = line.find('#');
    if (h != std::string::npos) line.erase(h);
    size_t eq = line.find('=');
    if (eq == std::string::npos) continue;
    std::string k = trim(line.substr(0, eq)), v = trim(line.substr(eq + 1));
    if (v.empty()) continue;
    if (k == "client") c.client = v;
    else if (k == "port") c.port = v;
  }
  return c;
}

Conf load_conf(const std::string& dir) {
  std::ifstream f(dir + "/panel.conf");
  std::stringstream ss;
  if (f) ss << f.rdbuf();
  return parse_conf(ss.str());
}

#ifdef PANEL_NO_ALSA

namespace {
struct NullIo : Io {
  bool connect() override { return false; }
  bool alive() override { return false; }
  void disconnect() override {}
  bool send(const std::vector<uint8_t>&) override { return false; }
  int recv(std::vector<uint8_t>&, int) override { return 0; }
};
}  // namespace
#ifndef PANEL_TEST_IO  // tests that need a scripted link define make_alsa_io themselves
std::unique_ptr<Io> make_alsa_io(const Conf&) { return std::unique_ptr<Io>(new NullIo); }
#endif

#else

namespace {

class AlsaIo : public Io {
 public:
  explicit AlsaIo(const Conf& c) : conf_(c) {}
  ~AlsaIo() override {
    if (seq_) snd_seq_close(seq_);
  }

  bool connect() override {
    if (!open_client()) return false;
    int client = -1, port = -1;
    if (!find_peer(client, port)) return false;
    // Subscriptions are per sequencer port: drop stale ones before adding (EBUSY just means "already there").
    snd_seq_disconnect_to(seq_, port_, client, port);
    snd_seq_disconnect_from(seq_, port_, client, port);
    int a = snd_seq_connect_to(seq_, port_, client, port);
    int b = snd_seq_connect_from(seq_, port_, client, port);
    if ((a < 0 && a != -EBUSY) || (b < 0 && b != -EBUSY)) return false;
    peer_client_ = client;
    peer_port_ = port;
    pending_.clear();
    return true;
  }

  bool alive() override {
    if (!seq_ || peer_client_ < 0) return false;
    snd_seq_client_info_t* ci;
    snd_seq_client_info_alloca(&ci);
    if (snd_seq_get_any_client_info(seq_, peer_client_, ci) < 0) return false;
    if (conf_.client != snd_seq_client_info_get_name(ci)) return false;
    snd_seq_port_info_t* pi;
    snd_seq_port_info_alloca(&pi);
    return snd_seq_get_any_port_info(seq_, peer_client_, peer_port_, pi) >= 0;
  }

  void disconnect() override {
    if (seq_ && peer_client_ >= 0) {
      snd_seq_disconnect_to(seq_, port_, peer_client_, peer_port_);
      snd_seq_disconnect_from(seq_, port_, peer_client_, peer_port_);
    }
    peer_client_ = peer_port_ = -1;
    pending_.clear();
  }

  bool send(const std::vector<uint8_t>& sysex) override {
    if (!seq_ || peer_client_ < 0 || sysex.empty()) return false;
    snd_seq_event_t ev;
    snd_seq_ev_clear(&ev);
    snd_seq_ev_set_source(&ev, port_);
    snd_seq_ev_set_dest(&ev, peer_client_, peer_port_);
    snd_seq_ev_set_direct(&ev);
    snd_seq_ev_set_sysex(&ev, static_cast<unsigned>(sysex.size()), const_cast<uint8_t*>(sysex.data()));
    return snd_seq_event_output_direct(seq_, &ev) >= 0;
  }

  int recv(std::vector<uint8_t>& chunk, int timeout_ms) override {
    if (!seq_) return -1;
    if (pending_.empty()) {
      struct pollfd fds[4];
      int n = snd_seq_poll_descriptors(seq_, fds, 4, POLLIN);
      if (n > 0) {
        if (poll(fds, n, timeout_ms) < 0) return -1;
        unsigned short re = 0;
        snd_seq_poll_descriptors_revents(seq_, fds, n, &re);
        if (re & (POLLERR | POLLHUP | POLLNVAL)) return -1;  // the caller backs off instead of spinning
      }
      snd_seq_event_t* ev = nullptr;
      while (snd_seq_event_input(seq_, &ev) >= 0 && ev) {
        if (ev->type == SND_SEQ_EVENT_SYSEX) {
          const uint8_t* p = static_cast<const uint8_t*>(ev->data.ext.ptr);
          pending_.emplace_back(p, p + ev->data.ext.len);
        }
        if (snd_seq_event_input_pending(seq_, 0) <= 0) break;
      }
    }
    if (pending_.empty()) return 0;
    chunk = std::move(pending_.front());
    pending_.pop_front();
    return 1;
  }

 private:
  bool open_client() {
    if (seq_) return true;
    if (snd_seq_open(&seq_, "default", SND_SEQ_OPEN_DUPLEX, SND_SEQ_NONBLOCK) < 0) { seq_ = nullptr; return false; }
    snd_seq_set_client_name(seq_, "rpi-audio panel");
    port_ = snd_seq_create_simple_port(seq_, "control", SND_SEQ_PORT_CAP_READ | SND_SEQ_PORT_CAP_WRITE |
                                       SND_SEQ_PORT_CAP_SUBS_READ | SND_SEQ_PORT_CAP_SUBS_WRITE,
                                       SND_SEQ_PORT_TYPE_MIDI_GENERIC | SND_SEQ_PORT_TYPE_APPLICATION);
    if (port_ < 0) { snd_seq_close(seq_); seq_ = nullptr; return false; }
    return true;
  }

  // The client named conf_.client; its port named conf_.port, else its lowest-numbered port.
  bool find_peer(int& client, int& port) {
    snd_seq_client_info_t* ci;
    snd_seq_client_info_alloca(&ci);
    snd_seq_client_info_set_client(ci, -1);
    while (snd_seq_query_next_client(seq_, ci) >= 0) {
      int c = snd_seq_client_info_get_client(ci);
      if (c == snd_seq_client_id(seq_) || conf_.client != snd_seq_client_info_get_name(ci)) continue;
      snd_seq_port_info_t* pi;
      snd_seq_port_info_alloca(&pi);
      snd_seq_port_info_set_client(pi, c);
      snd_seq_port_info_set_port(pi, -1);
      int first = -1;
      while (snd_seq_query_next_port(seq_, pi) >= 0) {
        unsigned caps = snd_seq_port_info_get_capability(pi);
        if ((caps & SND_SEQ_PORT_CAP_NO_EXPORT) || !(caps & SND_SEQ_PORT_CAP_READ) || !(caps & SND_SEQ_PORT_CAP_WRITE))
          continue;
        int p = snd_seq_port_info_get_port(pi);
        if (first < 0) first = p;
        if (conf_.port == snd_seq_port_info_get_name(pi)) { client = c; port = p; return true; }
      }
      if (first >= 0) { client = c; port = first; return true; }
    }
    return false;
  }

  Conf conf_;
  snd_seq_t* seq_ = nullptr;
  int port_ = -1, peer_client_ = -1, peer_port_ = -1;
  std::deque<std::vector<uint8_t>> pending_;
};

}  // namespace

std::unique_ptr<Io> make_alsa_io(const Conf& conf) { return std::unique_ptr<Io>(new AlsaIo(conf)); }

#endif

}  // namespace panel
