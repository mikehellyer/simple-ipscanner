import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from simple_ipscanner.core import arp, ping  # noqa: E402
from simple_ipscanner.core.history import GONE, ScanHistory  # noqa: E402
from simple_ipscanner.core.ping import PingReply  # noqa: E402
from simple_ipscanner.core.scanner import HostResult  # noqa: E402
from simple_ipscanner.core.settings import DeviceBook, SettingsStore  # noqa: E402
from simple_ipscanner.core.watch import DOWN, OFFLINE  # noqa: E402
from simple_ipscanner.gui import style  # noqa: E402
from simple_ipscanner.gui.results_model import CHANGE, IP, ResultsFilter, ResultsModel  # noqa: E402

# One for the whole module: Qt objects collected after the app is gone
# can crash at exit.
APP = QApplication.instance() or QApplication([])


def _model(history):
    model = ResultsModel()
    model.start(["10.0.0.1", "10.0.0.2", "10.0.0.3"], history, lambda ip, mac: "")
    proxy = ResultsFilter()
    proxy.setSourceModel(model)
    return model, proxy


def test_gone_device_is_highlighted_and_kept_in_view(tmp_path):
    history = ScanHistory(tmp_path / "h.json")
    history.record([HostResult("10.0.0.1", True, hostname="tv"), HostResult("10.0.0.2", True)])
    model, proxy = _model(history)
    model.set_result(HostResult("10.0.0.1", False), history.change_for("10.0.0.1", False), "")
    model.set_result(HostResult("10.0.0.2", True, 3.0), history.change_for("10.0.0.2", True), "")
    model.set_result(HostResult("10.0.0.3", False), history.change_for("10.0.0.3", False), "")
    row = model.row_for("10.0.0.1")
    assert row.change == GONE
    index = model.index(0, CHANGE)
    assert model.data(index).startswith("Switched off")
    assert model.data(model.index(0, 2)) == "tv"  # the name it had when it was on
    assert model.data(index, role=8).color().name() == style.GONE_ROW  # Qt.BackgroundRole
    proxy.set_show("alive")
    assert proxy.rowCount() == 2  # the one that's on, and the one that went off
    proxy.set_show("changes")
    assert proxy.rowCount() == 1
    proxy.set_show("all")
    assert proxy.rowCount() == 3


def test_main_window_scans_and_watches(tmp_path, monkeypatch):
    from simple_ipscanner.gui import main_window as mw

    monkeypatch.setattr(ping, "icmp_available", lambda: True)
    monkeypatch.setattr(ping, "is_alive", lambda ip, t=1000, f=True: PingReply(ip.endswith(".2"), 2.0, 64, "ping"))
    monkeypatch.setattr(ping, "resolve_hostname", lambda ip: "")
    monkeypatch.setattr(arp, "read_neighbours", lambda: {})
    monkeypatch.setattr(mw, "check_for_update", lambda *a: None)
    store = SettingsStore(tmp_path / "settings.json")
    store.update(range_text="10.0.0.1-3", watch_interval_s=3600)
    history = ScanHistory(tmp_path / "last_scan.json")
    history.record([HostResult("10.0.0.1", True)])
    window = mw.MainWindow(store, history, DeviceBook(tmp_path / "devices.json"))
    try:
        window._start_scan()
        scanner = window._scanner
        assert scanner.finished.wait(10)
        window._drain_scan()
        assert window._scanner is None
        assert window._model.row_for("10.0.0.1").change == GONE
        assert "1 switched off since last scan" in window._status.text()
        assert ScanHistory(tmp_path / "last_scan.json").get("10.0.0.2")["alive"]

        window._set_watch("10.0.0.2", OFFLINE, "Printer")
        assert "Watching (1)" == window._tabs.tabText(1)
        played = []
        window._beeper.play = lambda kind, times=1: played.append(kind)
        window._monitor.results.put(("10.0.0.2", True, 2.0))
        window._monitor.results.put(("10.0.0.2", False, None))
        window._monitor.results.put(("10.0.0.2", False, None))
        window._drain_watch()
        assert window._watches.items["10.0.0.2"].state == DOWN
        assert played == ["offline"]
        assert not window._alarm.isHidden()
        assert DeviceBook(tmp_path / "devices.json").watches[0]["ip"] == "10.0.0.2"
    finally:
        window.close()


def test_csv_export_defuses_formulas():
    from simple_ipscanner.gui.main_window import csv_safe

    assert csv_safe('=HYPERLINK("http://evil","x")').startswith("'=")
    assert csv_safe("@SUM(1)") == "'@SUM(1)"
    assert csv_safe("printer.lan") == "printer.lan"
    assert csv_safe("12 ms") == "12 ms"


def test_hostnames_never_become_tooltips(tmp_path):
    history = ScanHistory(tmp_path / "h.json")
    model, _ = _model(history)
    model.set_result(HostResult("10.0.0.1", True, 1.0, method="ping", hostname="<img src=x>"), None, "")
    assert model.data(model.index(0, 2)) == "<img src=x>"  # shown, as plain text in the table
    assert model.data(model.index(0, 2), role=3) is None  # Qt.ToolTipRole
