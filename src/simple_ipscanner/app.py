import sys

from simple_ipscanner import __version__


def self_test() -> int:
    """`Simple-IPScanner --self-test`: checks a built app has everything it
    needs bundled (the release workflow runs this on each OS). Exit code
    0 if so."""
    checks = {}
    try:
        from simple_ipscanner.core import iprange

        checks["ranges"] = len(iprange.parse_range("10.0.0.0/24")) == 254
    except Exception:
        checks["ranges"] = False
    try:
        from simple_ipscanner.core import vendors

        checks["maker list"] = vendors.vendor_for("B8:27:EB:00:00:00") != ""
    except Exception:
        checks["maker list"] = False
    try:
        from simple_ipscanner.core import sound

        checks["sounds"] = len(sound.tone_wav(sound.OFFLINE_NOTES)) > 1000
    except Exception:
        checks["sounds"] = False
    try:
        import psutil

        checks["network info"] = bool(psutil.net_if_addrs())
    except Exception:
        checks["network info"] = False
    try:
        import certifi
        from simple_ipscanner.core.http import SSL_CONTEXT  # noqa: F401

        checks["certificates"] = bool(certifi.where())
    except Exception:
        checks["certificates"] = False
    report_text = ", ".join(f"{name}: {'ok' if ok else 'MISSING'}" for name, ok in checks.items())
    try:
        print(f"Simple-IPScanner {__version__} self-test — {report_text}", flush=True)
    except (AttributeError, OSError):  # no console (Windows GUI build)
        pass
    return 0 if all(checks.values()) else 1


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    # Qt is imported only now, so --self-test runs even where there's no
    # display or graphics libraries (the release workflow's build machines).
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from simple_ipscanner.core.diagnostics import enable_app_log, enable_crash_log, log_event
    from simple_ipscanner.core.history import ScanHistory
    from simple_ipscanner.core.settings import DeviceBook, SettingsStore
    from simple_ipscanner.gui import style
    from simple_ipscanner.gui.main_window import ICON_PATH, MainWindow

    enable_app_log(__version__)
    enable_crash_log()
    app = QApplication(sys.argv)
    app.setApplicationName("Simple-IPScanner")
    app.setDesktopFileName("simple-ipscanner")
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    style.apply(app)
    settings = SettingsStore()
    window = MainWindow(settings, ScanHistory(settings.directory / "last_scan.json"),
                        DeviceBook(settings.directory / "devices.json"))
    window.show()
    code = app.exec()
    log_event(f"event loop finished (code {code})")
    return code


if __name__ == "__main__":
    sys.exit(main())
