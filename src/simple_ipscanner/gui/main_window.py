"""The main window: the range box and Scan button, the results table and
the Watching tab, the alarm and update banners, and the menus."""
from __future__ import annotations

import csv
import sys
import time
import webbrowser
from pathlib import Path

from PySide6.QtCore import QByteArray, QPoint, Qt, QTimer
from PySide6.QtGui import QAction, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QFileDialog, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QProgressBar,
                               QPushButton, QTableView, QTabWidget, QVBoxLayout, QWidget)

from simple_ipscanner import __version__
from simple_ipscanner.core import iprange, ping
from simple_ipscanner.core.history import GONE, ScanHistory
from simple_ipscanner.core.scanner import ScanOptions, Scanner, scan_one
from simple_ipscanner.core.self_update import (UpdateVerificationError, download_asset,
                                               find_asset_for_this_platform, launch_installer)
from simple_ipscanner.core.settings import DeviceBook
from simple_ipscanner.core.updater import check_for_update
from simple_ipscanner.core.watch import BOTH, OFFLINE, ONLINE, WatchList, WatchMonitor
from simple_ipscanner.gui.alarm import AlarmBanner, Beeper
from simple_ipscanner.gui.ping_dialog import PingDialog
from simple_ipscanner.gui.results_model import COLUMNS, IP, ResultsFilter, ResultsModel
from simple_ipscanner.gui.settings_dialog import SettingsDialog
from simple_ipscanner.gui.update_banner import UpdateBanner
from simple_ipscanner.gui.watch_panel import AddWatchDialog, WatchPanel
from simple_ipscanner.gui.workers import BackgroundRunner

ICON_PATH = Path(__file__).parent / "resources" / "icon.png"
UPDATE_OWNER = "mikehellyer"
UPDATE_REPO = "simple-ipscanner"
BACKGROUND_JOIN_TIMEOUT_MS = 3000
SHOW_CHOICES = [("alive", "Devices that are on"), ("all", "Every address"), ("changes", "Only changes since last scan")]


class MainWindow(QMainWindow):
    def __init__(self, settings_store, history: ScanHistory, book: DeviceBook):
        super().__init__()
        self._store = settings_store
        self._settings = settings_store.settings
        self._history = history
        self._book = book
        self._runner = BackgroundRunner(self)
        self._scanner: Scanner | None = None
        self._pending_update = None
        self._own_ip = iprange.local_address()

        self.setWindowTitle("Simple-IPScanner")
        self.resize(1100, 680)
        if self._settings.geometry:
            self.restoreGeometry(QByteArray.fromHex(self._settings.geometry.encode()))

        # --- watching
        self._watches = WatchList(self._settings.misses_needed)
        self._watches.load_json(self._book.watches)
        self._monitor = WatchMonitor(self._settings.watch_interval_s, self._settings.timeout_ms)
        self._monitor.set_targets(self._watches.ips())
        self._monitor.start()
        self._beeper = Beeper(self._settings.beep_volume)

        # --- the top bar
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Range:"))
        self._range = QLineEdit()
        self._range.setPlaceholderText("e.g. 192.168.1.1 - 192.168.1.254, or 192.168.1.0/24")
        self._range.setText(self._settings.range_text)
        self._range.returnPressed.connect(self._toggle_scan)
        bar.addWidget(self._range, stretch=1)
        mine = QPushButton("My network")
        mine.setToolTip("Fill in this computer's own network")
        mine.clicked.connect(self._use_my_network)
        bar.addWidget(mine)
        self._scan_button = QPushButton("Scan")
        self._scan_button.setObjectName("primary")
        self._scan_button.clicked.connect(self._toggle_scan)
        bar.addWidget(self._scan_button)
        bar.addSpacing(12)
        bar.addWidget(QLabel("Show:"))
        self._show = QComboBox()
        for key, text in SHOW_CHOICES:
            self._show.addItem(text, key)
        self._show.setCurrentIndex([k for k, _ in SHOW_CHOICES].index(self._settings.show))
        self._show.currentIndexChanged.connect(self._on_show_changed)
        bar.addWidget(self._show)
        ping_button = QPushButton("Ping…")
        ping_button.setToolTip("Ping the selected device, or any address")
        ping_button.clicked.connect(lambda: self._open_ping(self._selected_ip()))
        bar.addWidget(ping_button)

        # --- banners
        self._update_banner = UpdateBanner()
        self._update_banner.update_clicked.connect(self._start_update)
        self._alarm = AlarmBanner(self._beeper)
        self._alarm.repeat = self._settings.beep_until_silenced

        # --- results
        self._model = ResultsModel(self)
        self._proxy = ResultsFilter(self)
        self._proxy.setSourceModel(self._model)
        self._proxy.set_show(self._settings.show)
        self._table = QTableView()
        self._table.setModel(self._proxy)
        self._table.setSortingEnabled(True)
        self._table.sortByColumn(IP, Qt.AscendingOrder)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().hide()
        self._table.verticalHeader().setDefaultSectionSize(26)
        self._table.setShowGrid(False)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(True)
        for col, width in enumerate([180, 70, 160, 110, 140, 180, 90, 100, 200]):
            self._table.setColumnWidth(col, width)
        if self._settings.header_state:
            header.restoreState(QByteArray.fromHex(self._settings.header_state.encode()))
        self._table.setContextMenuPolicy(Qt.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._results_menu)
        self._table.doubleClicked.connect(lambda index: self._open_ping(self._ip_at(index)))

        self._empty = QLabel()
        self._empty.setProperty("role", "muted")
        self._empty.setAlignment(Qt.AlignCenter)
        self._empty.setWordWrap(True)

        results_page = QWidget()
        results_layout = QVBoxLayout(results_page)
        results_layout.setContentsMargins(0, 8, 0, 0)
        results_layout.addWidget(self._empty)
        results_layout.addWidget(self._table, stretch=1)

        self._watch_panel = WatchPanel(self._watches)
        self._watch_panel.add_requested.connect(lambda: self._watch_dialog(""))
        self._watch_panel.remove_requested.connect(self._unwatch)
        self._watch_panel.mode_changed.connect(lambda ip, mode: self._set_watch(ip, mode))
        self._watch_panel.ping_requested.connect(self._open_ping)
        self._watch_panel.test_beep.connect(lambda: self._beeper.play("offline"))
        self._watch_panel.pause_toggled.connect(self._on_pause_toggled)

        self._tabs = QTabWidget()
        self._tabs.addTab(results_page, "Scan results")
        self._tabs.addTab(self._watch_panel, "Watching")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(12, 10, 12, 6)
        layout.addLayout(bar)
        layout.addWidget(self._update_banner)
        layout.addWidget(self._alarm)
        layout.addWidget(self._tabs, stretch=1)
        self.setCentralWidget(central)

        self._status = QLabel()
        self.statusBar().addWidget(self._status, 1)
        # Passing notes go on the right, rather than through showMessage(),
        # which would cover the scan's progress text.
        self._note = QLabel()
        self._note.setProperty("role", "muted")
        self.statusBar().addPermanentWidget(self._note)
        self._note_timer = QTimer(self)
        self._note_timer.setSingleShot(True)
        self._note_timer.timeout.connect(self._note.clear)
        self._progress = QProgressBar()
        self._progress.setFixedWidth(200)
        self._progress.setTextVisible(False)
        self._progress.hide()
        self.statusBar().addPermanentWidget(self._progress)

        self._build_menus()
        self._update_watch_views()
        self._show_idle_status()

        self._scan_timer = QTimer(self)
        self._scan_timer.setInterval(100)
        self._scan_timer.timeout.connect(self._drain_scan)
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(250)
        self._watch_timer.timeout.connect(self._drain_watch)
        self._watch_timer.start()
        self._since_timer = QTimer(self)
        self._since_timer.setInterval(5000)
        self._since_timer.timeout.connect(self._watch_panel.refresh)
        self._since_timer.start()

        if not self._range.text():
            self._use_my_network()
        self._runner.run(ping.icmp_available, self._on_icmp_checked, lambda error: None)
        QTimer.singleShot(3000, self._check_for_updates)

    # --- menus

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        export = file_menu.addAction("Export results…")
        export.setShortcut(QKeySequence.Save)
        export.triggered.connect(self._export)
        file_menu.addSeparator()
        quit_action = file_menu.addAction("Quit")
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)

        scan_menu = self.menuBar().addMenu("Scan")
        self._scan_action = QAction("Start scan", self)
        self._scan_action.setShortcut("F5")
        self._scan_action.triggered.connect(self._toggle_scan)
        scan_menu.addAction(self._scan_action)
        scan_menu.addAction("Scan my network", lambda: (self._use_my_network(), self._start_scan()))
        scan_menu.addSeparator()
        scan_menu.addAction("Forget previous scans…", self._forget_history)

        tools = self.menuBar().addMenu("Tools")
        ping_action = tools.addAction("Ping a device…", lambda: self._open_ping(self._selected_ip()))
        ping_action.setShortcut("Ctrl+P")
        tools.addAction("Watch a device…", lambda: self._watch_dialog(self._selected_ip()))
        tools.addSeparator()
        tools.addAction("Settings…", self._open_settings)

        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction("Check for updates", lambda: self._check_for_updates(tell=True))
        help_menu.addAction("About Simple-IPScanner", self._about)

    # --- scanning

    def _use_my_network(self) -> None:
        network = iprange.local_network()
        if network is None:
            self._status.setText("Couldn't work out this computer's network — type a range instead")
            return
        self._own_ip = network.address
        self._range.setText(network.range_text())

    def _options(self) -> ScanOptions:
        s = self._settings
        try:
            ports = ping.parse_ports(s.ports_text)
        except ValueError:
            ports = []
        return ScanOptions(s.threads, s.timeout_ms, ports, s.tcp_fallback, s.resolve_names)

    def _toggle_scan(self) -> None:
        if self._scanner is not None:
            self._scanner.cancel()
            self._scan_button.setEnabled(False)
            self._status.setText("Stopping…")
        else:
            self._start_scan()

    def _start_scan(self) -> None:
        if self._scanner is not None:
            return
        try:
            addresses = iprange.parse_range(self._range.text())
        except iprange.RangeError as error:
            QMessageBox.warning(self, "Range", str(error)[0].upper() + str(error)[1:])
            return
        if len(addresses) > 4096:
            answer = QMessageBox.question(
                self, "Big range", f"That's {len(addresses):,} addresses, which could take a while. Scan anyway?")
            if answer != QMessageBox.Yes:
                return
        self._store.update(range_text=self._range.text().strip())
        self._model.start(addresses, self._history, self._book.name_for)
        self._model.set_watch_modes({ip: w.mode for ip, w in self._watches.items.items()})
        self._scanner = Scanner(addresses, self._options(), self._own_ip)
        self._scanner.start()
        self._scan_timer.start()
        self._progress.setRange(0, len(addresses))
        self._progress.setValue(0)
        self._progress.show()
        self._scan_button.setText("Stop")
        self._scan_button.setObjectName("stop")
        self._scan_button.style().polish(self._scan_button)
        self._scan_action.setText("Stop scan")
        self._tabs.setCurrentIndex(0)
        self._update_empty_hint()

    def _drain_scan(self) -> None:
        scanner = self._scanner
        if scanner is None:
            return
        while not scanner.results.empty():
            result = scanner.results.get()
            change = self._history.change_for(result.ip, result.alive)
            self._model.set_result(result, change, self._book.name_for(result.ip, result.mac))
        total = len(scanner.addresses)
        self._progress.setValue(scanner.done_count)
        if scanner.finished.is_set() and scanner.results.empty():
            self._finish_scan(scanner)
        else:
            self._status.setText(f"Scanning… {scanner.done_count} of {total} · {self._counts()}")
        self._update_empty_hint()

    def _counts(self) -> str:
        rows = self._model.rows
        on = sum(1 for r in rows if r.alive)
        gone = sum(1 for r in rows if r.change == GONE)
        came = sum(1 for r in rows if r.change and r.change != GONE)
        text = f"{on} on"
        if gone:
            text += f" · {gone} switched off since last scan"
        if came:
            text += f" · {came} switched on"
        return text

    def _finish_scan(self, scanner: Scanner) -> None:
        self._scan_timer.stop()
        self._scanner = None
        self._history.record(self._model.scanned_results(), scanner.started_at)
        seconds = scanner.ended_at - scanner.started_at
        done = "Stopped after" if scanner.cancelled.is_set() else "Scanned"
        self._status.setText(f"{done} {len(self._model.scanned_results())} of {len(scanner.addresses)} addresses "
                             f"in {seconds:.1f} s · {self._counts()}")
        self._progress.hide()
        self._scan_button.setEnabled(True)
        self._scan_button.setText("Scan")
        self._scan_button.setObjectName("primary")
        self._scan_button.style().polish(self._scan_button)
        self._scan_action.setText("Start scan")
        self._update_empty_hint()

    def _show_idle_status(self) -> None:
        last = max((e.get("scanned", 0) for e in self._history.entries.values()), default=0)
        if last:
            on = sum(1 for e in self._history.entries.values() if e.get("alive") and e.get("scanned") == last)
            when = time.strftime("%d %b at %H:%M", time.localtime(last))
            self._status.setText(f"Last scan {when}: {on} devices on. Scan again to see what's changed.")
        else:
            self._status.setText("Click Scan to find the devices on your network.")
        self._update_empty_hint()

    def _update_empty_hint(self) -> None:
        if not self._model.rows:
            text = "Click Scan to find the devices on your network."
        elif self._proxy.rowCount() == 0:
            text = "Nothing to show yet." if self._scanner else (
                "No changes since the last scan." if self._proxy.show == "changes" else "No devices found.")
        else:
            text = ""
        self._empty.setText(text)
        self._empty.setVisible(bool(text))

    def _on_show_changed(self) -> None:
        show = self._show.currentData()
        self._proxy.set_show(show)
        self._store.update(show=show)
        self._update_empty_hint()

    def _forget_history(self) -> None:
        answer = QMessageBox.question(
            self, "Forget previous scans",
            "Forget what earlier scans found? The next scan won't show anything as switched off or on.")
        if answer == QMessageBox.Yes:
            self._history.forget()
            self._show_idle_status()

    def _flash(self, text: str, ms: int) -> None:
        self._note.setText(text)
        self._note_timer.start(ms)

    def _on_icmp_checked(self, available: bool) -> None:
        if not available:
            self._flash(
                "Ping (ICMP) isn't allowed here — finding devices by TCP and ARP instead", 15000)

    # --- the results table

    def _ip_at(self, proxy_index) -> str:
        if not proxy_index.isValid():
            return ""
        return self._model.rows[self._proxy.mapToSource(proxy_index).row()].ip

    def _selected_ips(self) -> list[str]:
        return [self._ip_at(i) for i in self._table.selectionModel().selectedRows()]

    def _selected_ip(self) -> str:
        if self._tabs.currentIndex() == 1:
            return ""
        ips = self._selected_ips()
        return ips[0] if ips else ""

    def _results_menu(self, pos: QPoint) -> None:
        index = self._table.indexAt(pos)
        if not index.isValid():
            return
        ips = self._selected_ips() or [self._ip_at(index)]
        ip = self._ip_at(index) if self._ip_at(index) in ips else ips[0]
        row = self._model.row_for(ip)
        menu = QMenu(self)
        menu.addAction(f"Ping {ip}…", lambda: self._open_ping(ip))
        menu.addAction("Rescan", lambda: [self._rescan(i) for i in ips])
        watch = menu.addMenu("Watch — beep when it…")
        current = self._watches.items.get(ip)
        for mode, text in ((OFFLINE, "Goes offline"), (ONLINE, "Comes online"), (BOTH, "Goes offline or comes online")):
            action = watch.addAction(text, lambda m=mode: [self._set_watch(i, m) for i in ips])
            action.setCheckable(True)
            action.setChecked(bool(current and current.mode == mode))
        if any(i in self._watches.items for i in ips):
            watch.addSeparator()
            watch.addAction("Stop watching", lambda: [self._unwatch(i) for i in ips])
        menu.addAction("Name this device…", lambda: self._rename(ip))
        menu.addSeparator()
        menu.addAction("Open in web browser", lambda: webbrowser.open(f"http://{ip}/"))
        menu.addAction("Copy IP address", lambda: QGuiApplication.clipboard().setText("\n".join(ips)))
        if row and row.mac:
            menu.addAction("Copy MAC address", lambda: QGuiApplication.clipboard().setText(row.mac))
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _rescan(self, ip: str) -> None:
        options, own = self._options(), self._own_ip
        self._runner.run(lambda: scan_one(ip, options, own), self._on_rescanned, lambda error: None)

    def _on_rescanned(self, result) -> None:
        row = self._model.row_for(result.ip)
        # Compared with the last full scan, as the row already was.
        change = row.change if row and row.result is not None and row.alive == result.alive else \
            self._history.change_for(result.ip, result.alive)
        self._model.set_result(result, change, self._book.name_for(result.ip, result.mac))

    def _rename(self, ip: str) -> None:
        row = self._model.row_for(ip)
        mac = row.mac if row else ""
        name, ok = QInputDialog.getText(self, "Name this device", f"Name for {ip}:", text=self._book.name_for(ip, mac))
        if ok:
            self._book.set_name(ip, mac, name)
            self._model.set_name(ip, name.strip())
            if ip in self._watches.items:
                self._watches.items[ip].name = name.strip()
                self._save_watches()

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export results", "ip-scan.csv", "CSV files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(COLUMNS)
                for r in range(self._proxy.rowCount()):
                    writer.writerow([self._proxy.index(r, c).data() or "" for c in range(len(COLUMNS))])
        except OSError as error:
            QMessageBox.warning(self, "Export", f"Couldn't save the file: {error}")
            return
        self._flash(f"Saved {self._proxy.rowCount()} rows to {path}", 5000)

    # --- ping

    def _open_ping(self, ip: str = "") -> None:
        label = self._watches.items[ip].label() if ip in self._watches.items else ""
        row = self._model.row_for(ip) if ip else None
        if not label and row and row.name:
            label = f"{row.name} ({ip})"
        dialog = PingDialog(ip, label, self._settings.timeout_ms, self)
        dialog.watch_requested.connect(self._watch_dialog)
        dialog.show()

    # --- watching

    def _watch_dialog(self, ip: str = "") -> None:
        row = self._model.row_for(ip) if ip else None
        current = self._watches.items.get(ip)
        name = current.name if current else (row.name if row else "")
        dialog = AddWatchDialog(ip, name, current.mode if current else OFFLINE, self)
        if dialog.exec():
            ip, name, mode = dialog.values()
            self._set_watch(ip, mode, name)
            self._tabs.setCurrentIndex(1)

    def _set_watch(self, ip: str, mode: str, name: str = "") -> None:
        if not name:
            existing = self._watches.items.get(ip)
            row = self._model.row_for(ip)
            name = (existing.name if existing else "") or (row.name if row else "") or \
                self._book.name_for(ip, row.mac if row else "")
        is_new = ip not in self._watches.items
        self._watches.add(ip, mode, name)
        self._save_watches()
        if is_new:
            self._watch_panel.rebuild()
            self._monitor.check_now()
        self._update_watch_views()

    def _unwatch(self, ip: str) -> None:
        self._watches.remove(ip)
        self._save_watches()
        self._watch_panel.rebuild()
        self._update_watch_views()

    def _save_watches(self) -> None:
        self._book.watches = self._watches.to_json()
        self._book.save()
        self._monitor.set_targets(self._watches.ips())

    def _update_watch_views(self) -> None:
        self._model.set_watch_modes({ip: w.mode for ip, w in self._watches.items.items()})
        count = len(self._watches.items)
        self._tabs.setTabText(1, f"Watching ({count})" if count else "Watching")

    def _drain_watch(self) -> None:
        changed = False
        while not self._monitor.results.empty():
            ip, alive, ms = self._monitor.results.get()
            event = self._watches.observe(ip, alive, ms)
            changed = True
            if event is not None:
                self._flash(f"{time.strftime('%H:%M:%S')} — {event.text()}", 30000)
                if event.alert:
                    self._alarm.raise_alarm(event)
        if changed:
            self._watch_panel.refresh()

    def _on_pause_toggled(self, paused: bool) -> None:
        self._monitor.paused = paused
        if not paused:
            self._monitor.check_now()

    # --- settings

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self._settings, self)
        if not dialog.exec():
            return
        self._store.update(**dialog.changes())
        s = self._settings
        self._watches.misses_needed = s.misses_needed
        self._monitor.interval_s = s.watch_interval_s
        self._monitor.timeout_ms = s.timeout_ms
        self._beeper.set_volume(s.beep_volume)
        self._alarm.repeat = s.beep_until_silenced
        self._monitor.check_now()

    def _about(self) -> None:
        QMessageBox.about(
            self, "About Simple-IPScanner",
            f"<b>Simple-IPScanner</b> {__version__}<br><br>Finds the devices on your network, pings them, and "
            "beeps when one goes offline or comes online.<br><br>MAC address makers from the IEEE registry.")

    # --- closing

    def closeEvent(self, event) -> None:
        self._store.update(
            geometry=bytes(self.saveGeometry().toHex()).decode(),
            header_state=bytes(self._table.horizontalHeader().saveState().toHex()).decode(),
        )
        if self._scanner is not None:
            self._scanner.cancel()
        self._monitor.halt()
        self._beeper.stop()
        self._runner.shutdown(BACKGROUND_JOIN_TIMEOUT_MS)
        super().closeEvent(event)
        QApplication.quit()

    def quit(self) -> None:
        self.close()

    # --- updates

    def _check_for_updates(self, tell: bool = False) -> None:
        self._runner.run(
            lambda: check_for_update(__version__, UPDATE_OWNER, UPDATE_REPO),
            lambda info: self._on_update_checked(info, tell),
            lambda error: self._flash("Couldn't check for updates", 5000) if tell else None,
        )

    def _on_update_checked(self, info, tell: bool = False) -> None:
        if info:
            self._pending_update = info
            self._update_banner.announce(info.version)
        elif tell:
            self._flash(f"Simple-IPScanner v{__version__} is the latest version", 5000)

    def _start_update(self) -> None:
        if self._pending_update is None:
            return
        asset_url = find_asset_for_this_platform(self._pending_update.assets, UPDATE_OWNER, UPDATE_REPO)
        if asset_url is None:
            self._update_banner.set_status(f"No installer for this platform — see {self._pending_update.url}")
            return
        self._update_banner.set_busy(True, "Downloading…")
        self._runner.run(lambda: download_asset(asset_url), self._on_update_downloaded,
                         lambda error: self._on_update_downloaded(None))

    def _on_update_downloaded(self, path) -> None:
        if path is None:
            self._update_banner.set_status("Couldn't download the update — try again")
            self._update_banner.set_busy(False)
            return
        try:
            process = launch_installer(path, expected_version=self._pending_update.version)
        except UpdateVerificationError as error:
            self._update_banner.set_status(f"Update not installed — {error}")
            self._update_banner.set_busy(False)
            return
        except OSError:
            self._update_banner.set_status(f"Downloaded to {path} — open it manually")
            self._update_banner.set_busy(False)
            return

        self._update_banner.set_status("Installer launched — closing to finish…")
        if sys.platform not in ("win32", "darwin") and process is not None:
            # Linux: wait for pkexec/apt to finish before quitting — quitting
            # immediately can kill its password prompt before it's answered.
            self._runner.run(lambda: (path, self._wait_for_installer(process)), self._on_installer_finished)
        else:
            QTimer.singleShot(1500, self.quit)

    @staticmethod
    def _wait_for_installer(process) -> tuple[int, str]:
        returncode = process.wait()
        stderr_text = process.stderr.read().strip() if process.stderr is not None else ""
        return returncode, stderr_text

    def _on_installer_finished(self, result) -> None:
        path, (returncode, stderr_text) = result
        if returncode == 0:
            self.quit()
            return
        detail = f": {stderr_text}" if stderr_text else f" (exit code {returncode})"
        self._update_banner.set_status(f"Update didn't install{detail} — installer is at {path}")
        self._update_banner.set_busy(False)

