# Tracker USB IN prearm experiment

This is an **experimental patch for track3r-os**. It passed the static image gate and was tested on the Tracker on 2026-11-04. **It did not fix the Pi 4's multichannel USB losses.** The original firmware has been restored and stereo capture rechecked without losses; do not install this patch expecting clean multichannel audio. The source experiment lives in an isolated checkout, separate from the user's Tracker development tree.

The patch gives the two isochronous IN buffer descriptors separate packet storage and keeps both prepared. The existing driver prepares one packet at a time. With two prepared packets, the controller can answer the next frame's poll even if the interrupt handling the previous completion has not run yet. Feedback scheduling and the OUT path are unchanged.

Costs and limits:

- One extra `InPacketBuffer`, approximately 1 KiB of SRAM_U. Check the final target linker map and memory gate before a device trial.
- One additional queued packet and one additional priming packet. At startup or after both descriptors empty, the handler may build two packets instead of one. Check worst interrupt time and stream latency on the target.
- This does not create USB bus bandwidth or prove that delayed device interrupts cause the observed losses. Eleven channels was rejected by the Pi controller before streaming began.

`0001-prearm-two-iso-in-packets.patch` modifies the device header, adjusts the existing IN startup expectations and adds a test that delays the completion interrupt over two host polls. It checks all six supported channel layouts, separate storage, nonzero frame/channel sample order, interrupt recovery and ping-pong bookkeeping. The patch also registers the isochronous suite for QEMU and adds its test label. Existing endpoint, audio ordering, return, stop/restart and bus-reset tests remain in the targeted test run.

The patch passes `git apply --check` against the public source tree containing the running v1.1.0 source (`a3fe987526ec`). The relevant source files are unchanged in that public checkout. In the host experiment, all 13 targeted cases pass with the patch; the existing implementation passes the original 12 cases and fails the added delayed-interrupt case. This demonstrates the extra tolerance in the model, not a measured repair of the physical link.

The bench image passed 13 focused host cases, 150 USB cases with ASan/UBSan, 20 target ctests, three Cortex-M4F QEMU USB suites, two byte-identical target builds, nine image checks and the flash-configuration check. The actual SRAM_U delta is 1024 bytes after alignment, leaving 944 bytes beyond the reserved 24 KiB stack and 32 KiB free floor.

On the unit, 2 channels remained clean; 4/6/8/10 channels still lost 203/448/161/12 packets respectively in approximately 20 seconds each. Small differences from the previous matrix are not proof of an improvement. Capture already fails acceptance, so this candidate is not integrated or retained as a solution; further firmware experiments need a new hypothesis and hardware comparison.

Evidence and limits: [code investigation](../../../docs/hw/2026-11-04-tracker-usb-code.md), [hardware experiment](../../../docs/hw/2026-11-04-tracker-prearm-hardware.md).
