// SPDX-License-Identifier: GPL-3.0-or-later
// SDK peer used by test_native_network.py. No audio hardware or JACK required.
#include <ableton/LinkAudio.hpp>
#include <atomic>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <thread>
int main() {
    const char *requested = std::getenv("RPI_LINK_TEST_PEER");
    const std::string peer = requested ? requested : "rpi-audio";
    std::atomic<unsigned> buffers{0}, rate{0}, channels{0};
    std::atomic<int> left{0}, right{0};
    ableton::LinkAudio link(120, "rpi-audio-test-receiver");
    link.enable(true);
    link.enableLinkAudio(true);
    std::unique_ptr<ableton::LinkAudioSource> source;
    for (unsigned n = 0; n < 150; ++n) {
        if (!source) {
            for (const auto &channel : link.channels()) {
                if (channel.name != "Network mix" || channel.peerName != peer) continue;
                source = std::make_unique<ableton::LinkAudioSource>(link, channel.id, [&](auto buffer) {
                    rate.store(buffer.info.sampleRate); channels.store(buffer.info.numChannels);
                    int l = 0, r = 0;
                    for (unsigned f = 0; f < buffer.info.numFrames && buffer.info.numChannels == 2; ++f) {
                        l = std::max(l, std::abs(static_cast<int>(buffer.samples[f * 2])));
                        r = std::max(r, std::abs(static_cast<int>(buffer.samples[f * 2 + 1])));
                    }
                    left.store(std::max(left.load(), l)); right.store(std::max(right.load(), r));
                    buffers.fetch_add(1);
                });
                break;
            }
        }
        if (buffers.load() >= 50 && left.load() > 8000 && right.load() > 16000) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    source.reset();
    std::cout << "{\"buffers\":" << buffers.load() << ",\"rate\":" << rate.load()
              << ",\"channels\":" << channels.load() << ",\"left\":" << left.load()
              << ",\"right\":" << right.load() << "}\n";
    return buffers.load() >= 50 && rate.load() == 48000 && channels.load() == 2 &&
           left.load() == 8192 && right.load() == 16384 ? 0 : 1;
}
