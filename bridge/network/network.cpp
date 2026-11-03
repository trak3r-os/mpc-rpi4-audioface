// SPDX-License-Identifier: GPL-3.0-or-later
// JACK output adapters. Network/file operations are outside the realtime callback.
#include <jack/jack.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#include <atomic>
#include <array>
#include <algorithm>
#include <chrono>
#include <cmath>
#include <csignal>
#include <cstdint>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <memory>
#include <random>
#include <stdexcept>
#include <string>
#include <thread>
#ifdef WITH_LINK
#include <ableton/LinkAudio.hpp>
#include <ableton/link/HostTimeFilter.hpp>
#endif

using Clock = std::chrono::steady_clock;
constexpr uint32_t Capacity = 65536;
constexpr unsigned PacketFrames = 48;
struct Frame { float left, right; uint64_t index; };
struct Engine {
    jack_client_t *client{};
    jack_port_t *ports[2]{};
    uint32_t rate{};
    std::array<Frame, Capacity> ring{};
    std::atomic<uint32_t> write{0}, read{0};
    std::atomic<uint64_t> dropped{0}, buffers{0}, xruns{0};
    std::atomic<bool> alive{true};
    uint64_t sampleTime{};
    uint32_t lastCycle{};
    std::atomic<uint32_t> baseFrame{0};
    std::atomic<bool> started{false};
    bool useLink{};
#ifdef WITH_LINK
    std::unique_ptr<ableton::LinkAudio> link;
    std::unique_ptr<ableton::LinkAudioSink> sink;
    ableton::link::HostTimeFilter<ableton::LinkAudio::Clock> timeFilter;
#endif
};
static volatile sig_atomic_t stopping;
static void stop(int) { stopping = 1; }
static void shutdown(void *arg) { static_cast<Engine *>(arg)->alive.store(false); }
static int xrun(void *arg) { static_cast<Engine *>(arg)->xruns.fetch_add(1); return 0; }
static int16_t pcm(float value) {
    if (!std::isfinite(value)) return 0;
    return static_cast<int16_t>(std::lrint(std::clamp(value, -1.0f, 32767.0f / 32768) * 32768));
}
static int process(jack_nframes_t frames, void *arg) {
    auto &e = *static_cast<Engine *>(arg);
    const auto cycle = jack_last_frame_time(e.client);
    if (!e.started.load(std::memory_order_relaxed)) {
        e.lastCycle = cycle;
        e.baseFrame.store(cycle, std::memory_order_relaxed);
        e.started.store(true, std::memory_order_release);
    }
    e.sampleTime += static_cast<uint32_t>(cycle - e.lastCycle);
    e.lastCycle = cycle;
    auto *left = static_cast<const float *>(jack_port_get_buffer(e.ports[0], frames));
    auto *right = static_cast<const float *>(jack_port_get_buffer(e.ports[1], frames));
#ifdef WITH_LINK
    if (e.useLink) {
        const auto now = e.timeFilter.sampleTimeToHostTime(static_cast<double>(e.sampleTime));
        auto state = e.link->captureAudioSessionState();
        ableton::LinkAudioSink::BufferHandle buffer{*e.sink};
        if (buffer && frames * 2 <= buffer.maxNumSamples) {
            for (unsigned n = 0; n < frames; ++n) {
                buffer.samples[n * 2] = pcm(left[n]);
                buffer.samples[n * 2 + 1] = pcm(right[n]);
            }
            if (buffer.commit(state, state.beatAtTime(now, 4), 4, frames, 2, e.rate)) e.buffers.fetch_add(1);
        }
        return 0;
    }
#endif
    const auto write = e.write.load(std::memory_order_relaxed);
    const auto read = e.read.load(std::memory_order_acquire);
    if (frames > Capacity - (write - read)) {
        e.dropped.fetch_add(frames);
        return 0;
    }
    for (unsigned n = 0; n < frames; ++n)
        e.ring[(write + n) % Capacity] = {left[n], right[n], e.sampleTime + n};
    e.write.store(write + frames, std::memory_order_release);
    return 0;
}
static void be16(uint8_t *p, uint16_t value) { p[0] = value >> 8; p[1] = value; }
static void be32(uint8_t *p, uint32_t value) {
    p[0] = value >> 24; p[1] = value >> 16; p[2] = value >> 8; p[3] = value;
}
static sockaddr_in target(const std::string &address, unsigned port) {
    sockaddr_in out{};
    out.sin_family = AF_INET; out.sin_port = htons(port);
    if (inet_pton(AF_INET, address.c_str(), &out.sin_addr) != 1) throw std::runtime_error("Invalid IPv4 address");
    return out;
}
static void senderReport(int socket, sockaddr_in destination, uint32_t ssrc, uint32_t timestamp,
                         uint32_t packets, uint32_t octets) {
    // Compound RTCP sender report + SDES CNAME, RFC 3550.
    std::array<uint8_t, 64> report{};
    report[0] = 0x80; report[1] = 200; be16(report.data() + 2, 6); be32(report.data() + 4, ssrc);
    const auto nanos = std::chrono::duration_cast<std::chrono::nanoseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    be32(report.data() + 8, static_cast<uint32_t>(nanos / 1000000000 + 2208988800ULL));
    be32(report.data() + 12, static_cast<uint32_t>((nanos % 1000000000) * 4294967296ULL / 1000000000));
    be32(report.data() + 16, timestamp); be32(report.data() + 20, packets); be32(report.data() + 24, octets);
    report[28] = 0x81; report[29] = 202; be16(report.data() + 30, 6); be32(report.data() + 32, ssrc);
    const std::string cname = "rpi-audio@local";
    report[36] = 1; report[37] = cname.size();
    std::memcpy(report.data() + 38, cname.data(), cname.size());
    sendto(socket, report.data(), 56, MSG_DONTWAIT, reinterpret_cast<sockaddr *>(&destination), sizeof destination);
}
int main(int argc, char **argv) {
    std::string transport = "rtp", clientName = "network_rtp_out", address = "239.69.1.1", sdp;
    std::string peerName = "rpi-audio";
    unsigned port = 5004, ttl = 1;
    try {
        for (int n = 1; n < argc; ++n) {
            std::string option = argv[n];
            if (option == "--capabilities") {
                std::cout << "{\"rtp\":true,\"link\":"
#ifdef WITH_LINK
                          << "true"
#else
                          << "false"
#endif
                          << "}\n";
                return 0;
            }
            if (++n >= argc) throw std::runtime_error("Missing argument");
            std::string value = argv[n];
            if (option == "--transport") transport = value;
            else if (option == "--client") clientName = value;
            else if (option == "--peer") peerName = value;
            else if (option == "--address") address = value;
            else if (option == "--port") port = std::stoul(value);
            else if (option == "--ttl") ttl = std::stoul(value);
            else if (option == "--sdp") sdp = value;
            else throw std::runtime_error("Unknown option");
        }
        if ((transport != "rtp" && transport != "link") || port < 1024 || port > 65534 || port % 2 || ttl < 1 || ttl > 32)
            throw std::runtime_error("Invalid transport, port or TTL");
#ifndef WITH_LINK
        if (transport == "link") throw std::runtime_error("Link Audio support was not built");
#endif
        auto engine = std::make_unique<Engine>();
        auto &e = *engine;
        e.useLink = transport == "link";
        const auto destination = target(address, port);
        jack_status_t status{};
        const char *server = std::getenv("JACK_DEFAULT_SERVER");
        jack_client_t *client = jack_client_open(clientName.c_str(),
            static_cast<jack_options_t>(JackNoStartServer | JackUseExactName | (server ? JackServerName : 0)), &status, server);
        if (!client) throw std::runtime_error("JACK server is not available");
        e.client = client;
        e.rate = jack_get_sample_rate(client);
        for (unsigned n = 0; n < 2; ++n) {
            const auto name = "playback_" + std::to_string(n + 1);
            e.ports[n] = jack_port_register(client, name.c_str(), JACK_DEFAULT_AUDIO_TYPE, JackPortIsInput, 0);
            if (!e.ports[n]) { jack_client_close(client); throw std::runtime_error("Cannot register JACK port"); }
        }
#ifdef WITH_LINK
        if (e.useLink) {
            e.link = std::make_unique<ableton::LinkAudio>(120, peerName);
            e.sink = std::make_unique<ableton::LinkAudioSink>(*e.link, "Network mix", 32768);
            e.link->enable(true);
            e.link->enableLinkAudio(true);
        }
#endif
        int udp = -1;
        if (!e.useLink) {
            udp = socket(AF_INET, SOCK_DGRAM, 0);
            if (udp < 0) { jack_client_close(client); throw std::runtime_error("Cannot create UDP socket"); }
            const auto ttlByte = static_cast<unsigned char>(ttl);
            setsockopt(udp, IPPROTO_IP, IP_MULTICAST_TTL, &ttlByte, sizeof ttlByte);
            if (!sdp.empty()) {
                std::ofstream description(sdp);
                const bool multicast = IN_MULTICAST(ntohl(destination.sin_addr.s_addr));
                description << "v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=rpi-audio network mix\r\n"
                            << "c=IN IP4 " << address << (multicast ? "/" + std::to_string(ttl) : "")
                            << "\r\nt=0 0\r\nm=audio " << port << " RTP/AVP 96\r\n"
                            << "a=rtpmap:96 L16/" << e.rate << "/2\r\na=sendonly\r\n";
                if (!description) { close(udp); jack_client_close(client); throw std::runtime_error("Cannot write SDP"); }
            }
        }
        signal(SIGINT, stop); signal(SIGTERM, stop);
        jack_set_process_callback(client, process, &e);
        jack_set_xrun_callback(client, xrun, &e);
        jack_on_shutdown(client, shutdown, &e);
        if (jack_activate(client)) { if (udp >= 0) close(udp); jack_client_close(client); return 1; }
        std::random_device random;
        const uint32_t ssrc = random(), offset = random();
        uint16_t sequence = random();
        uint32_t packets = 0, octets = 0, timestamp = offset;
        uint64_t previousBuffers = 0;
        auto nextReport = Clock::now();
        while (!stopping && e.alive.load()) {
            if (!e.useLink) {
                unsigned processed = 0;
                while (processed++ < 256) {
                    auto read = e.read.load(std::memory_order_relaxed);
                    const auto write = e.write.load(std::memory_order_acquire);
                    if (write - read < PacketFrames) break;
                    std::array<uint8_t, 12 + PacketFrames * 4> packet{};
                    packet[0] = 0x80; packet[1] = 96;
                    be16(packet.data() + 2, sequence++);
                    timestamp = offset + e.ring[read % Capacity].index;
                    be32(packet.data() + 4, timestamp); be32(packet.data() + 8, ssrc);
                    unsigned frames = 0;
                    for (; frames < PacketFrames; ++frames) {
                        const auto &frame = e.ring[(read + frames) % Capacity];
                        if (offset + static_cast<uint32_t>(frame.index) != timestamp + frames) break;
                        be16(packet.data() + 12 + frames * 4, static_cast<uint16_t>(pcm(frame.left)));
                        be16(packet.data() + 14 + frames * 4, static_cast<uint16_t>(pcm(frame.right)));
                    }
                    e.read.store(read + frames, std::memory_order_release);
                    const auto size = 12 + frames * 4;
                    if (sendto(udp, packet.data(), size, MSG_DONTWAIT,
                               reinterpret_cast<const sockaddr *>(&destination), sizeof destination) == size) {
                        ++packets; octets += frames * 4;
                    } else e.dropped.fetch_add(frames);
                }
            }
            if (Clock::now() >= nextReport) {
                const auto count = e.buffers.load();
                std::string state = packets ? "sending" : "waiting";
                unsigned peers = 0;
#ifdef WITH_LINK
                if (e.useLink) { peers = e.link->numPeers(); state = count > previousBuffers ? "sending" : "waiting"; }
#endif
                std::cout << "{\"event\":\"status\",\"state\":\"" << state << "\",\"peers\":" << peers
                          << ",\"packets\":" << packets << ",\"buffers\":" << count << ",\"rate\":" << e.rate
                          << (e.useLink ? "" : ",\"queue_frames\":" + std::to_string(e.write.load() - e.read.load()) +
                              ",\"capacity_frames\":" + std::to_string(Capacity))
                          << ",\"xruns\":" << e.xruns.load() << ",\"dropped_frames\":" << e.dropped.load() << "}\n"
                          << std::flush;
                previousBuffers = count;
                if (udp >= 0 && e.started.load(std::memory_order_acquire)) {
                    const auto currentTimestamp = offset + jack_frame_time(client) - e.baseFrame.load();
                    senderReport(udp, target(address, port + 1), ssrc, currentTimestamp, packets, octets);
                }
                nextReport = Clock::now() + std::chrono::seconds(1);
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
        }
        jack_client_close(client);
        if (udp >= 0) close(udp);
    } catch (const std::exception &error) {
        std::cout << "{\"event\":\"status\",\"state\":\"error\",\"error\":"
                  << std::quoted(error.what()) << "}\n" << std::flush;
        std::cerr << "network adapter: " << error.what() << '\n';
        return 1;
    }
    return 0;
}
