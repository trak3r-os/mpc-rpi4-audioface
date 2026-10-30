// SPDX-License-Identifier: GPL-3.0-or-later
// Worker thread: owns the MIDI link and drives Core. Started by the constructor, joined by the destructor.
#pragma once
#include <atomic>
#include <memory>
#include <thread>

#include "panel_core.h"
#include "panel_io.h"
#include "panel_protocol.h"

namespace panel {

class Engine {
 public:
  Engine(std::unique_ptr<Io> io, CoreConfig cfg = {}, Core::Log log = {}, Core::Clock clock = {});
  ~Engine();
  Core& core() { return core_; }

 private:
  void run();
  int64_t now() const { return clock_(); }

  Core::Clock clock_;
  Core core_;
  std::unique_ptr<Io> io_;
  Core::Log log_;
  SysexAssembler asm_;
  std::atomic<bool> stop_{false};
  std::thread thread_;
};

}  // namespace panel
