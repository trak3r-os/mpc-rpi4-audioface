// SPDX-License-Identifier: GPL-3.0-or-later
#include "panel_engine.h"

#include <chrono>
#include <thread>

namespace panel {
namespace {
int64_t steady_ms() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch())
      .count();
}
}  // namespace

Engine::Engine(std::unique_ptr<Io> io, CoreConfig cfg, Core::Log log, Core::Clock clock)
    : clock_(clock ? clock : Core::Clock(steady_ms)), core_(cfg, log, clock_), io_(std::move(io)), log_(std::move(log)) {
  core_.begin(now());
  thread_ = std::thread([this] { run(); });
}

Engine::~Engine() {
  stop_ = true;
  if (thread_.joinable()) thread_.join();
}

void Engine::run() {
  const int retry = core_.config().retry_ms;
  bool connected = false;
  int64_t next_try = 0, next_alive = 0;
  while (!stop_) {
    int64_t t = now();
    if (!connected) {
      if (t >= next_try) {
        next_try = t + retry;
        if (io_->connect()) {
          connected = true;
          asm_.reset();
          next_alive = t + retry;
          core_.link_up(t);
        }
      }
    } else if (t >= next_alive) {
      next_alive = t + retry;
      if (!io_->alive()) {
        io_->disconnect();
        connected = false;
        next_try = t + retry;
        core_.link_down(t);
      }
    }
    core_.tick(t);
    std::string cmd;
    while (connected && core_.next_command(t, cmd)) {
      std::vector<uint8_t> msg = encode_command(cmd);
      if (msg.empty() || !io_->send(msg)) {
        if (log_) log_("cannot send: " + cmd);
        if (!msg.empty()) {  // a failed write means the port is gone: let the next check find out
          next_alive = t;
        }
      }
    }
    if (!connected) {
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
      continue;
    }
    std::vector<uint8_t> chunk;
    int r = io_->recv(chunk, 20);
    if (r < 0) {
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
    } else if (r > 0) {
      std::string text;
      if (asm_.feed(chunk.data(), chunk.size(), text)) core_.on_reply(text, now());
    }
  }
  if (connected) io_->disconnect();
}

}  // namespace panel
