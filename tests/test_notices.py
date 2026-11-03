# SPDX-License-Identifier: GPL-3.0-or-later
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "bridge/rpi-audio-ui"))
import notices  # noqa: E402
import ui  # noqa: E402


def hardware(devices=(), wifi="up", usb="not attached"):
    return {"devices": list(devices), "wifi": {"state": wifi, "name": "bender_5G"}, "usb_state": usb}


DEVICE = {"identity": "card:GP150", "card": "GP150", "name": "Guitar", "in": {"channels": 2}}


def test_no_startup_notices_and_connection_events_expire_and_can_be_dismissed():
    notifier = notices.Notifier()
    assert notifier.read({}, {}, 0) == ()
    assert notifier.read({}, hardware(), 1) == ()
    assert notifier.read({}, hardware([DEVICE]), 2) == ("+ Guitar", "Capture only")
    assert notifier.changed
    assert notifier.read({}, hardware([DEVICE]), 3) == ("+ Guitar", "Capture only")
    assert not notifier.changed
    assert notifier.read({}, hardware([DEVICE]), 6) == ()
    assert notifier.read({}, hardware(), 7) == ("- Guitar", "Device disconnected")
    notifier.dismiss()
    assert notifier.read({}, hardware(), 7.1) == ()


def test_routing_identity_changes_do_not_announce_a_second_physical_device():
    notifier = notices.Notifier()
    notifier.read({}, hardware([DEVICE]), 0)
    status = {"devices": [{**DEVICE, "identity": "usb-serial", "in": {"running": True, "channels": 2}}]}
    assert notifier.read(status, hardware([DEVICE]), 1) == ()


def test_network_usb_and_blocked_notices_are_bounded_and_not_repeated():
    notifier = notices.Notifier()
    notifier.read({}, hardware(wifi="down"), 0)
    assert notifier.read({}, hardware(usb="configured"), 1)[0] == "WiFi connected"
    assert notifier.read({}, hardware(usb="configured"), 4.1)[0] == "USB host connected"
    notifier.dismiss()
    blocked = {"devices": [{**DEVICE, "in": {"blocked": "USB full-speed budget: needs 900 B", "channels": 2}}]}
    title, detail = notifier.read(blocked, hardware([DEVICE], usb="configured"), 5)
    # The physical connection is announced first, then its actionable error.
    assert title == "+ Guitar"
    assert notifier.read(blocked, hardware([DEVICE], usb="configured"), 8.1) == (
        "USB full: Guitar", "Unplug unused device")
    assert notifier.read(blocked, hardware([DEVICE], usb="configured"), 12) == ()
    for n in range(30):
        notifier.read({}, hardware(usb="configured" if n % 2 else "not attached"), 12 + n * 0.01)
    assert len(notifier.queue) <= 8


def test_notification_preserves_selected_row_and_footer():
    interface = ui.UI()
    for _ in range(5):
        interface.handle("cw", {})
    interface.notification = ("+ Guitar", "Audio + MIDI")
    rows = interface.render({})
    assert any(row.selected and "Connections" in row.text for row in rows[1:5])
    assert rows[5].text.strip() == "+ Guitar" and rows[6].text.strip() == "Audio + MIDI"
    assert rows[7].footer
