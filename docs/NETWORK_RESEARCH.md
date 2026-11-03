# Network-audio projects to evaluate

Research snapshot: 3 November 2026. This shortlist informed the implemented RTP/PCM and official-SDK Link Audio senders. Other listed adapters and full AES67 remain research options; no receiver certification is implied. The [output implementation](OUTPUTS.md) records test coverage and limits; the [user guide](MANUAL.md) explains operation.

## Practical conclusion

Use **Link Audio** for direct Ableton interoperability, with `rpi-linkaudio` as a useful reference. Use **AES67** as the professional interoperability target, with a separate prototype and receiver tests. A JACK-to-network adapter should join the existing graph rather than compete for an ALSA device already opened by a bridge.

Classic Link, Link Audio, RTP, AES67, AOO and Zita's network format are different interfaces. A shared Ethernet connection does not make them interchangeable.

## Shortlist

| Project | What it provides | Evidence and fit | Main limitation |
|---|---|---|---|
| [Ableton/link](https://github.com/Ableton/link) | Official C++ Link and Link Audio implementation and examples | Public [Link Audio API](https://ableton.github.io/link/) supports publishing and subscribing to audio channels | We still need a JACK adapter, clock mapping, buffering and actual ARM64/Live interoperability tests |
| [ty-art-ty/rpi-linkaudio](https://github.com/ty-art-ty/rpi-linkaudio) | Stereo USB-audio capture on a Pi, published as a Link Audio peer | README describes Pi 4/5, 64-bit OS, an ARM build check and a hardware-to-Live 12.4 Ethernet test; [CMake](https://github.com/ty-art-ty/rpi-linkaudio/blob/main/CMakeLists.txt) uses PortAudio and RtMidi | Sender, not a general router or documented receiver; no documented direct JACK backend. Its suggested Live receive buffer is not a measured end-to-end latency |
| [bondagit/aes67-linux-daemon](https://github.com/bondagit/aes67-linux-daemon) | AES67 source/sink control, discovery, API and web interface | README documents ARM targets and integration with the Ravenna ALSA module | Requires a matching kernel module and working PTP. This is not demonstrated on this Pi's Debian 13 / 6.18 kernel |
| [dewiweb/ALSA-RAVENNA-AES67-Driver](https://github.com/dewiweb/ALSA-RAVENNA-AES67-Driver) | Fork of the Ravenna/AES67 ALSA kernel driver | Relevant to understanding the daemon's PTP/RTP data path | Old fork; verify the exact maintained driver tree recommended by the daemon before attempting a build |
| [philhartung/aes67-sender](https://github.com/philhartung/aes67-sender) | Capture-to-network sender with documented JACK/ALSA options | README describes a Raspberry Pi 4 hardware experiment | README discusses Pi timing/jitter limitations with strict receivers; it does not establish universal AES67/Dante interoperability or provide our bidirectional router |
| [Zita-njbridge upstream](https://kokkinizita.linuxaudio.org/linuxaudio/) and [source mirror](https://github.com/digital-stage/zita-njbridge) | Multichannel JACK audio over its own UDP format, with adaptive receiver resampling | Fits our JACK architecture and permits independent audio clocks | Requires a compatible endpoint; it is not RTP/AES67 or a native Ableton receiver. Check upstream releases rather than treating an old mirror as the current release |
| [macdigi/force-link-audio](https://github.com/macdigi/force-link-audio) | Force-specific ALSA capture/interposition and a separate Link Audio sender | Useful example of separating audio capture from network publication; linked by Ableton's resource page | Specific to the Force/MockbaMod, not a drop-in Pi or JACK adapter |

The exact `rpi-linkaudio` URL above comes from the Resources section of Ableton's documentation. An earlier guessed URL was wrong; it is not evidence that the project is unavailable.

## Platform reach

[Ableton's guide](https://help.ableton.com/hc/en-us/articles/25425913328924-Link-Audio-FAQ) documents Link Audio from Live 12.4 and compatible devices. It is the receiving software's capabilities, not the words “PC” or “Mac”, that decide compatibility.

[SonoBus](https://sonobus.net/) is worth a second-stage evaluation for desktop/mobile use: it offers applications/plugins across multiple systems and documents JACK/ALSA on Linux. Its [Linux build instructions](https://github.com/sonosaurus/sonobus/blob/main/linux/BUILDING.md) also illustrate the extra application dependencies. SonoBus/AOO compatibility needs a matching receiver and a deliberate integration; it does not follow automatically from supporting Link Audio or AES67.

For standards-based audio, [AES67](https://www.aes.org/publications/standards/preview.cfm?ID=96) includes timing requirements beyond [RTP](https://www.rfc-editor.org/info/rfc3550/). Test PTP, the stream format, session description, packet timing and the selected receiver. Not all Dante devices implement AES67; [Dante's interoperability documentation](https://support.getdante.com/hc/en-gb/articles/5508253040927-AES67-Interoperability) is explicit about this.

## Repository metadata

The lightweight research agent checked public GitHub metadata. These are the last commit timestamps it reported, in UTC; they do not establish project quality, release support or interoperability. A mirror's commit date is not necessarily its upstream's latest release date.

| Repository | Last reported commit, UTC | License metadata / declaration |
|---|---|---|
| Ableton/link | 2026-10-15 11:04 | API returned `NOASSERTION`; use the actual license files for the chosen revision |
| ty-art-ty/rpi-linkaudio | 2026-05-31 13:37 | API: GPL-2.0; README describes GPL-2.0-or-later terms |
| bondagit/aes67-linux-daemon | 2026-10-25 09:02 | API: GPL-3.0 |
| philhartung/aes67-sender | 2023-10-13 18:56 | API: GPL-3.0 |
| digital-stage/zita-njbridge | 2021-03-10 20:03 | API: GPL-3.0; upstream releases must be checked separately |
| macdigi/force-link-audio | 2026-10-14 21:32 | API: GPL-2.0 |
| dewiweb/ALSA-RAVENNA-AES67-Driver | 2019-07-20 14:15 | No SPDX license identified by the API |

No source code from these repositories has been incorporated, built or deployed as part of this research. License metadata is recorded as reported, not normalized into a legal compatibility conclusion.

## First experiments

1. A user-space JACK ↔ Link Audio prototype: start with a stereo publication from a named, isolated JACK server. Read the official SDK and compare the small Pi sender, without reopening a USB interface the audio service owns.
2. Add receive buffering and sample-clock adaptation; test duplex against a real Live receiver. Measure end-to-end delay instead of treating a buffer setting as a measurement.
3. If two JACK endpoints are available, use Zita-njbridge as a separate network/clock experiment. This validates only its own transport.
4. For AES67, first select a concrete reference receiver and check the supported kernel/driver tree and PTP path. A user-space RTP sender can be a limited experiment, but must not be advertised as a conforming AES67 product merely because it sends packets.
5. Integrate proven adapters into the common destination model and ordinary-language menus. Verify local output continuity when a peer disappears.

No external project is a demonstrated replacement for the complete DAC + USB gadget + network routing engine. That combination still needs implementation and combined hardware tests.
