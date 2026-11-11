import wave
import io
from unittest.mock import patch

import pytest

from simple_ipscanner.core import arp, iprange, ping, sound, vendors
from simple_ipscanner.core.history import CAME, GONE, ScanHistory
from simple_ipscanner.core.pinger import ContinuousPinger, PingStats
from simple_ipscanner.core.ping import PingReply
from simple_ipscanner.core.scanner import HostResult, ScanOptions, Scanner
from simple_ipscanner.core.settings import DeviceBook, SettingsStore
from simple_ipscanner.core.watch import BOTH, DOWN, OFFLINE, ONLINE, UP, WatchList


# --- ranges

def test_parse_dash_range():
    assert iprange.parse_range("192.168.1.1 - 192.168.1.4") == [f"192.168.1.{n}" for n in range(1, 5)]


def test_parse_short_dash_range_and_reversed():
    assert iprange.parse_range("10.0.0.250-252") == ["10.0.0.250", "10.0.0.251", "10.0.0.252"]
    assert iprange.parse_range("10.0.0.3 - 10.0.0.1") == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]


def test_parse_cidr_skips_network_and_broadcast():
    hosts = iprange.parse_range("192.168.5.0/24")
    assert len(hosts) == 254 and hosts[0] == "192.168.5.1" and hosts[-1] == "192.168.5.254"


def test_parse_several_without_repeats():
    assert iprange.parse_range("10.0.0.2, 10.0.0.1-2; 10.0.0.9") == ["10.0.0.1", "10.0.0.2", "10.0.0.9"]


@pytest.mark.parametrize("text", ["", "hello", "10.0.0.1-300", "10.0.0.0/8", "1.2.3"])
def test_parse_rejects_nonsense(text):
    with pytest.raises(iprange.RangeError):
        iprange.parse_range(text)


def test_local_network_range_text_caps_big_networks():
    import ipaddress
    small = iprange.LocalNetwork("192.168.1.20", ipaddress.IPv4Network("192.168.1.0/24"))
    assert small.range_text() == "192.168.1.1 - 192.168.1.254"
    big = iprange.LocalNetwork("10.4.7.20", ipaddress.IPv4Network("10.0.0.0/8"))
    assert big.range_text() == "10.4.7.1 - 10.4.7.254"


# --- ping output

LINUX_REPLY = """PING 192.168.1.1 (192.168.1.1) 56(84) bytes of data.
64 bytes from 192.168.1.1: icmp_seq=1 ttl=64 time=2.48 ms
"""
WINDOWS_REPLY = "Reply from 192.168.1.1: bytes=32 time=3ms TTL=64\n"
WINDOWS_FAST = "Reply from 192.168.1.1: bytes=32 time<1ms TTL=128\n"
WINDOWS_UNREACHABLE = "Reply from 192.168.1.201: Destination host unreachable.\n"
GERMAN_REPLY = "Antwort von 192.168.1.1: Bytes=32 Zeit=4ms TTL=64\n"


def test_parse_linux_reply():
    reply = ping.parse_ping_output(LINUX_REPLY, 0)
    assert reply.alive and reply.ms == 2.48 and reply.ttl == 64


def test_parse_windows_replies():
    assert ping.parse_ping_output(WINDOWS_REPLY, 0).ms == 3
    fast = ping.parse_ping_output(WINDOWS_FAST, 0)
    assert fast.alive and fast.ms < 1 and "<1 ms" in fast.text
    assert ping.parse_ping_output(GERMAN_REPLY, 0).ms == 4


def test_windows_unreachable_is_not_alive_even_with_exit_code_0():
    assert not ping.parse_ping_output(WINDOWS_UNREACHABLE, 0).alive


def test_no_reply():
    assert not ping.parse_ping_output("1 packets transmitted, 0 received", 1).alive


def test_ping_command_per_platform():
    assert ping.ping_command("1.2.3.4", 1000, "win32")[1:] == ["-n", "1", "-w", "1000", "1.2.3.4"]
    assert ping.ping_command("1.2.3.4", 500, "darwin")[-3:] == ["-W", "500", "1.2.3.4"]
    assert ping.ping_command("1.2.3.4", 1500, "linux")[-3:] == ["-W", "1.5", "1.2.3.4"]


def test_parse_ports():
    assert ping.parse_ports("443, 22,80-82; 22") == [22, 80, 81, 82, 443]
    assert ping.parse_ports("") == []
    for bad in ("0", "70000", "1-5000", "http"):
        with pytest.raises(ValueError):
            ping.parse_ports(bad)


def test_tcp_probe_counts_a_refused_connection_as_alive():
    with patch("socket.create_connection", side_effect=ConnectionRefusedError):
        reply = ping.tcp_probe("10.0.0.5", ports=(80,))
    assert reply.alive and reply.method == "tcp:80"
    with patch("socket.create_connection", side_effect=TimeoutError):
        assert not ping.tcp_probe("10.0.0.5", ports=(80, 443)).alive


def test_is_alive_falls_back_to_tcp():
    with patch.object(ping, "icmp_available", return_value=True), \
            patch.object(ping, "icmp_ping", return_value=PingReply(False)), \
            patch.object(ping, "tcp_probe", return_value=PingReply(True, 3.0, None, "tcp:80")):
        assert ping.is_alive("10.0.0.5").method == "tcp:80"
        assert not ping.is_alive("10.0.0.5", tcp_fallback=False).alive


def test_is_alive_without_icmp_still_uses_tcp():
    with patch.object(ping, "icmp_available", return_value=False), \
            patch.object(ping, "tcp_probe", return_value=PingReply(True, 3.0, None, "tcp:80")):
        assert ping.is_alive("10.0.0.5", tcp_fallback=False).alive


# --- ARP and makers

def test_parse_proc_arp_skips_unanswered():
    text = """IP address       HW type     Flags       HW address            Mask     Device
192.168.1.254    0x1         0x2         d4:86:60:57:f0:a3     *        wlp0s20f3
192.168.1.3      0x1         0x0         00:00:00:00:00:00     *        wlp0s20f3
"""
    assert arp.parse_proc_arp(text) == {"192.168.1.254": "D4:86:60:57:F0:A3"}


def test_parse_ip_neigh_marks_only_reachable_as_confirmed():
    text = """192.168.1.254 dev wlp0s20f3 lladdr d4:86:60:57:f0:a3 REACHABLE
192.168.1.99 dev wlp0s20f3 lladdr 50:f5:da:c8:87:d2 STALE
192.168.1.3 dev wlp0s20f3 FAILED
192.168.1.4 dev wlp0s20f3 lladdr 00:11:22:33:44:55 FAILED
"""
    assert arp.parse_ip_neigh(text) == {
        "192.168.1.254": ("D4:86:60:57:F0:A3", True),
        "192.168.1.99": ("50:F5:DA:C8:87:D2", False),
    }


def test_parse_arp_a_mac_and_windows():
    mac = "? (192.168.1.1) at a4:2b:b0:1:2:3 on en0 ifscope [ethernet]\n? (224.0.0.251) at 1:0:5e:0:0:fb on en0\n"
    assert arp.parse_arp_a(mac) == {"192.168.1.1": "A4:2B:B0:01:02:03"}
    win = "  192.168.1.254         d4-86-60-57-f0-a3     dynamic\n  192.168.1.255  ff-ff-ff-ff-ff-ff  static\n"
    assert arp.parse_arp_a(win) == {"192.168.1.254": "D4:86:60:57:F0:A3"}


def test_vendor_lookup():
    assert "Raspberry Pi" in vendors.vendor_for("B8:27:EB:44:88:FD")
    assert vendors.vendor_for("3A:D3:67:02:FE:A2") == "(private address)"
    assert vendors.vendor_for("") == ""


# --- scanning

def test_scanner_reports_every_address(monkeypatch):
    def fake_alive(ip, timeout_ms, tcp):
        return PingReply(ip.endswith(".2"), 1.0 if ip.endswith(".2") else None, 64, "ping")

    monkeypatch.setattr(ping, "is_alive", fake_alive)
    monkeypatch.setattr(ping, "resolve_hostname", lambda ip: "printer.lan")
    monkeypatch.setattr(arp, "read_neighbours", lambda: {"10.0.0.2": ("B8:27:EB:00:00:01", True),
                                                         "10.0.0.3": ("B8:27:EB:00:00:02", True)})
    s = Scanner(["10.0.0.1", "10.0.0.2", "10.0.0.3"], ScanOptions(threads=4))
    s.start()
    assert s.finished.wait(10)
    final = {}
    while not s.results.empty():
        r = s.results.get()
        final[r.ip] = r
    assert set(final) == {"10.0.0.1", "10.0.0.2", "10.0.0.3"}
    assert final["10.0.0.2"].alive and final["10.0.0.2"].hostname == "printer.lan"
    assert "Raspberry Pi" in final["10.0.0.2"].vendor
    # ignored the ping but answered ARP just now: counted as on
    assert final["10.0.0.3"].alive and final["10.0.0.3"].method == "arp"
    assert not final["10.0.0.1"].alive


def test_scanner_never_changes_a_result_it_already_handed_over(monkeypatch):
    monkeypatch.setattr(ping, "is_alive", lambda ip, t, f: PingReply(True, 1.0, 64, "ping"))
    monkeypatch.setattr(ping, "resolve_hostname", lambda ip: "")
    monkeypatch.setattr(arp, "read_neighbours", lambda: {"10.0.0.1": ("B8:27:EB:00:00:01", True)})
    s = Scanner(["10.0.0.1"], ScanOptions(threads=1))
    s.start()
    assert s.finished.wait(10)
    first, second = s.results.get(), s.results.get()
    assert first.mac == "" and second.mac == "B8:27:EB:00:00:01"


def test_scanner_can_be_cancelled(monkeypatch):
    monkeypatch.setattr(ping, "is_alive", lambda ip, t, f: PingReply(False))
    monkeypatch.setattr(arp, "read_neighbours", lambda: {})
    s = Scanner([f"10.0.{n // 256}.{n % 256}" for n in range(2000)], ScanOptions(threads=2))
    s.cancel()
    s.start()
    assert s.finished.wait(10)
    assert s.done_count < 2000


# --- history: switched off / on since the last scan

def test_history_spots_devices_switched_off_and_on(tmp_path):
    path = tmp_path / "last_scan.json"
    h = ScanHistory(path)
    h.record([HostResult("10.0.0.1", True, hostname="tv", mac="AA:BB:CC:00:00:01"), HostResult("10.0.0.2", False)])
    h = ScanHistory(path)  # survives a restart
    assert h.change_for("10.0.0.1", False) == GONE
    assert h.change_for("10.0.0.1", True) is None
    assert h.change_for("10.0.0.2", True) == CAME
    assert h.change_for("10.0.0.9", True) is None  # never scanned before
    h.record([HostResult("10.0.0.1", False)])
    assert h.get("10.0.0.1")["hostname"] == "tv"  # still remembered for showing the gone device
    assert h.change_for("10.0.0.1", False) is None  # it was already off last time


def test_history_keeps_addresses_outside_this_scan(tmp_path):
    h = ScanHistory(tmp_path / "h.json")
    h.record([HostResult("10.0.0.1", True)])
    h.record([HostResult("10.0.0.2", True)])
    assert h.change_for("10.0.0.1", False) == GONE


# --- watching

def test_watch_beeps_only_after_enough_misses():
    w = WatchList(misses_needed=2)
    w.add("10.0.0.5", OFFLINE, "Printer")
    assert w.observe("10.0.0.5", True, 2.0, now=1) is None  # first look: no alarm
    assert w.items["10.0.0.5"].state == UP
    assert w.observe("10.0.0.5", False, now=2) is None  # one miss isn't enough
    event = w.observe("10.0.0.5", False, now=3)
    assert event is not None and event.went == DOWN and event.alert
    assert event.text() == "Printer (10.0.0.5) went offline"
    assert w.observe("10.0.0.5", False, now=4) is None  # still off: no repeat


def test_watch_online_mode():
    w = WatchList(misses_needed=1)
    w.add("10.0.0.5", ONLINE)
    w.observe("10.0.0.5", False, now=1)
    event = w.observe("10.0.0.5", True, 1.0, now=2)
    assert event.went == UP and event.alert
    event = w.observe("10.0.0.5", False, now=3)
    assert event.went == DOWN and not event.alert  # offline wasn't asked for


def test_watch_both_and_reply_resets_misses():
    w = WatchList(misses_needed=3)
    w.add("h", BOTH)
    w.observe("h", True, now=1)
    w.observe("h", False, now=2)
    w.observe("h", False, now=3)
    w.observe("h", True, now=4)
    assert w.observe("h", False, now=5) is None
    w.observe("h", False, now=6)
    assert w.observe("h", False, now=7).alert


def test_watch_list_round_trip():
    w = WatchList()
    w.add("10.0.0.5", BOTH, "NAS")
    w2 = WatchList()
    w2.load_json(w.to_json() + [{"ip": 5}, "junk", {"ip": "10.0.0.6", "mode": "nonsense"}])
    assert w2.items["10.0.0.5"].mode == BOTH and w2.items["10.0.0.5"].name == "NAS"
    assert w2.items["10.0.0.6"].mode == OFFLINE


# --- the ping window

def test_ping_stats():
    s = PingStats()
    for r in (PingReply(True, 2.0), PingReply(False), PingReply(True, 4.0), PingReply(True, 3.0)):
        s.add(r)
    assert s.sent == 4 and s.received == 3 and s.loss_percent == 25
    assert "min 2 / avg 3.0 / max 4 ms" in s.summary()


def test_continuous_pinger_counts():
    p = ContinuousPinger("10.0.0.1", interval_s=0, count=3, ping_fn=lambda ip, t: PingReply(True, 1.0, 64))
    p.start()
    p.join(5)
    assert [p.results.get()[0] for _ in range(3)] == [1, 2, 3]


# --- sounds, settings, names

def test_tone_wav_is_a_wav():
    data = sound.tone_wav([(440, 100), (0, 50)])
    with wave.open(io.BytesIO(data)) as w:
        assert w.getnframes() == int(sound.RATE * 0.15)


def test_settings_clamp_and_ignore_bad_types(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"threads": 9999, "show": "weird", "timeout_ms": "fast", "beep_until_silenced": true}')
    s = SettingsStore(path).settings
    assert s.threads == 256 and s.show == "alive" and s.timeout_ms == 1000 and s.beep_until_silenced


def test_device_names_follow_the_mac(tmp_path):
    book = DeviceBook(tmp_path / "devices.json")
    book.set_name("10.0.0.5", "AA:BB:CC:DD:EE:FF", "Printer")
    book = DeviceBook(tmp_path / "devices.json")
    assert book.name_for("10.0.0.77", "AA:BB:CC:DD:EE:FF") == "Printer"
    book.set_name("10.0.0.8", "", "Kettle")
    assert book.name_for("10.0.0.8") == "Kettle"
    book.set_name("10.0.0.8", "", "")
    assert book.name_for("10.0.0.8") == ""


# --- security

@pytest.mark.parametrize("target", ["-f", "-s65000", "--help", "1.2.3.4 -f", "a;b", "$(reboot)", "", "x" * 300,
                                    "host_name", "-1.2.3.4"])
def test_ping_refuses_anything_that_could_be_an_option(target):
    assert not ping.is_valid_target(target)
    with pytest.raises(ValueError):
        ping.ping_command(target, 1000, "linux")
    assert ping.icmp_ping(target).text == "not a valid address"


@pytest.mark.parametrize("target", ["192.168.1.1", "printer", "nas.local", "router.lan.", "my-pi-4"])
def test_ping_accepts_addresses_and_hostnames(target):
    assert ping.is_valid_target(target)


def test_windows_runs_ping_from_system32_not_the_current_folder(monkeypatch):
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    command = ping.ping_command("1.2.3.4", 1000, "win32")
    assert command[0].lower().endswith(r"system32\ping.exe") and command[0].lower().startswith("c:")


def test_watch_list_ignores_tampered_addresses():
    w = WatchList()
    w.load_json([{"ip": "-f"}, {"ip": "10.0.0.1"}])
    assert w.ips() == ["10.0.0.1"]


def test_history_ignores_values_of_the_wrong_type(tmp_path):
    path = tmp_path / "h.json"
    path.write_text('{"10.0.0.1": {"alive": true, "hostname": {"x": 1}, "seen": "yesterday", "evil": 1}}')
    assert ScanHistory(path).get("10.0.0.1") == {"alive": True}


def test_a_shared_mac_names_each_address_separately(tmp_path):
    # A Pi on Wi-Fi and a cable: Linux answers for both addresses with one
    # card's MAC, so naming one mustn't rename the other.
    book = DeviceBook(tmp_path / "devices.json")
    mac = "B8:27:EB:44:88:FD"
    book.set_name("192.168.1.192", mac, "Pi (cable)", mac_shared=True)
    book.set_name("192.168.1.238", mac, "Pi (Wi-Fi)", mac_shared=True)
    book = DeviceBook(tmp_path / "devices.json")
    assert book.name_for("192.168.1.192", mac) == "Pi (cable)"
    assert book.name_for("192.168.1.238", mac) == "Pi (Wi-Fi)"


def test_a_shared_mac_can_clear_one_address_name(tmp_path):
    book = DeviceBook(tmp_path / "devices.json")
    book.set_name("10.0.0.1", "AA:AA:AA:00:00:01", "Pi")  # named before the second connection appeared
    book.set_name("10.0.0.2", "AA:AA:AA:00:00:01", "", mac_shared=True)
    assert book.name_for("10.0.0.1", "AA:AA:AA:00:00:01") == "Pi"
    assert book.name_for("10.0.0.2", "AA:AA:AA:00:00:01") == ""
