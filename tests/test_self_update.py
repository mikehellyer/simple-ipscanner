import io
import subprocess
from unittest.mock import patch

import pytest

from simple_ipscanner.core.self_update import (
    UpdateVerificationError,
    download_asset,
    find_asset_for_this_platform,
    launch_installer,
    verify_deb,
)

DL = "https://github.com/mikehellyer/simple-ipscanner/releases/download/v0.2.0/"
ASSETS = [
    ("Simple-IPScanner-0.2.0-Windows-Setup.exe", DL + "Simple-IPScanner-0.2.0-Windows-Setup.exe"),
    ("Simple-IPScanner-0.2.0-macOS.dmg", DL + "Simple-IPScanner-0.2.0-macOS.dmg"),
    ("simple-ipscanner_0.2.0_amd64.deb", DL + "simple-ipscanner_0.2.0_amd64.deb"),
]


def find(assets):
    return find_asset_for_this_platform(assets, "mikehellyer", "simple-ipscanner")


def test_finds_windows_asset():
    with patch("sys.platform", "win32"):
        assert find(ASSETS) == ASSETS[0][1]


def test_finds_macos_asset():
    with patch("sys.platform", "darwin"):
        assert find(ASSETS) == ASSETS[1][1]


def test_finds_linux_asset():
    with patch("sys.platform", "linux"):
        assert find(ASSETS) == ASSETS[2][1]


def test_returns_none_when_no_matching_asset():
    with patch("sys.platform", "win32"):
        assert find(ASSETS[1:]) is None


def test_ignores_an_asset_linking_anywhere_but_this_repos_releases():
    elsewhere = [
        ("simple-ipscanner_0.2.0_amd64.deb", "https://evil.example/simple-ipscanner_0.2.0_amd64.deb"),
        ("simple-ipscanner_0.2.0_amd64.deb", "https://github.com/someone-else/simple-ipscanner/releases/download/v0.2.0/x.deb"),
    ]
    with patch("sys.platform", "linux"):
        assert find(elsewhere) is None


class _Response(io.BytesIO):
    def __init__(self, body, final_url="https://objects.githubusercontent.com/github-production-release-asset/1"):
        super().__init__(body)
        self._final_url = final_url

    def geturl(self):
        return self._final_url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


OPEN = "simple_ipscanner.core.http._OPENER.open"


def test_download_asset_writes_the_file(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.mkdtemp", lambda prefix="": str(tmp_path))
    with patch("sys.platform", "darwin"), patch(OPEN, return_value=_Response(b"installer bytes")):
        path = download_asset(DL + "Simple-IPScanner-0.2.0-macOS.dmg")

    assert path is not None
    assert path.name == "simple-ipscanner-update.dmg"  # fixed, not taken from the link
    assert path.read_bytes() == b"installer bytes"


def test_download_asset_returns_none_when_unreachable():
    with patch(OPEN, side_effect=OSError("network down")):
        assert download_asset(DL + "whatever.exe") is None


def test_download_asset_refuses_a_non_github_link():
    with patch(OPEN, return_value=_Response(b"x")) as mock_open:
        assert download_asset("https://evil.example/simple-ipscanner.deb") is None
    mock_open.assert_not_called()


def test_download_asset_refuses_a_redirect_away_from_github(tmp_path, monkeypatch):
    monkeypatch.setattr("tempfile.mkdtemp", lambda prefix="": str(tmp_path / "dl"))
    (tmp_path / "dl").mkdir()
    with patch(OPEN, return_value=_Response(b"x", final_url="https://evil.example/x.deb")):
        assert download_asset(DL + "simple-ipscanner_0.2.0_amd64.deb") is None
    assert not (tmp_path / "dl").exists()  # nothing left behind


def test_download_asset_refuses_an_implausibly_large_file(monkeypatch):
    monkeypatch.setattr("simple_ipscanner.core.self_update.MAX_INSTALLER_BYTES", 10)
    with patch(OPEN, return_value=_Response(b"x" * 11)):
        assert download_asset(DL + "simple-ipscanner_0.2.0_amd64.deb") is None


def _dpkg_fields(stdout, returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


def test_verify_deb_accepts_the_simple_ipscanner_package_at_the_expected_version():
    with patch("simple_ipscanner.core.self_update.shutil.which", return_value="/usr/bin/dpkg-deb"), patch(
        "simple_ipscanner.core.self_update.subprocess.run",
        return_value=_dpkg_fields("Package: simple-ipscanner\nVersion: 0.2.0\n"),
    ):
        verify_deb("/tmp/x.deb", "v0.2.0")


@pytest.mark.parametrize(
    "stdout,returncode",
    [
        ("Package: openssh-server\nVersion: 0.2.0\n", 0),
        ("Package: simple-ipscanner\nVersion: 0.1.9\n", 0),
        ("", 2),  # not a .deb at all
    ],
    ids=["other-package", "wrong-version", "not-a-deb"],
)
def test_verify_deb_rejects_anything_else(stdout, returncode):
    with patch("simple_ipscanner.core.self_update.shutil.which", return_value="/usr/bin/dpkg-deb"), patch(
        "simple_ipscanner.core.self_update.subprocess.run", return_value=_dpkg_fields(stdout, returncode)
    ):
        with pytest.raises(UpdateVerificationError):
            verify_deb("/tmp/x.deb", "v0.2.0")


def test_verify_deb_works_against_a_real_package(tmp_path):
    # Against an actual .deb built here, when the tools exist.
    import shutil as sh
    if not (sh.which("dpkg-deb")):
        pytest.skip("dpkg-deb not available")
    root = tmp_path / "pkg"
    (root / "DEBIAN").mkdir(parents=True)
    (root / "DEBIAN" / "control").write_text(
        "Package: simple-ipscanner\nVersion: 0.2.0\nArchitecture: all\n"
        "Maintainer: test <t@example.com>\nDescription: test\n"
    )
    deb = tmp_path / "test.deb"
    subprocess.run(["dpkg-deb", "--build", str(root), str(deb)], check=True, capture_output=True)
    verify_deb(deb, "v0.2.0")
    with pytest.raises(UpdateVerificationError):
        verify_deb(deb, "v0.3.0")


def test_launch_installer_linux_prefers_pkexec_apt_over_xdg_open():
    # Handing a local .deb to a desktop "Software" GUI via xdg-open is
    # unreliable across distros (some show "Uninstall" instead of
    # "Install"/"Upgrade" for an already-installed package name and do
    # nothing useful) — installing directly via apt is deterministic and
    # only prompts for a password once.
    def fake_which(name):
        return {"pkexec": "/usr/bin/pkexec", "apt": "/usr/bin/apt"}[name]

    with patch("simple_ipscanner.core.self_update.sys.platform", "linux"), patch(
        "simple_ipscanner.core.self_update.shutil.which", side_effect=fake_which
    ), patch("simple_ipscanner.core.self_update.verify_deb") as mock_verify, patch(
        "simple_ipscanner.core.self_update.subprocess.Popen"
    ) as mock_popen:
        result = launch_installer("/tmp/simple-ipscanner_1.2.3_amd64.deb", expected_version="v1.2.3")

    # Checked before it's installed as root.
    mock_verify.assert_called_once_with("/tmp/simple-ipscanner_1.2.3_amd64.deb", "v1.2.3")

    # Absolute paths, not bare "pkexec"/"apt": pkexec resolves the
    # command it's given using its own restricted environment rather
    # than the invoking shell's $PATH, and a bare "apt" name can fail to
    # resolve there (exit 127) even though `apt` works normally. stderr
    # is piped so a failure can show pkexec/apt's actual error text.
    mock_popen.assert_called_once_with(
        ["/usr/bin/pkexec", "/usr/bin/apt", "install", "-y", "/tmp/simple-ipscanner_1.2.3_amd64.deb"],
        stderr=subprocess.PIPE,
        text=True,
    )
    # The caller (main_window.py) waits on this before quitting, on
    # Linux, so quitting can't kill the pkexec password prompt before
    # it's answered.
    assert result is mock_popen.return_value


def test_launch_installer_linux_refuses_to_install_a_package_that_fails_its_check():
    def fake_which(name):
        return {"pkexec": "/usr/bin/pkexec", "apt": "/usr/bin/apt"}[name]

    with patch("simple_ipscanner.core.self_update.sys.platform", "linux"), patch(
        "simple_ipscanner.core.self_update.shutil.which", side_effect=fake_which
    ), patch(
        "simple_ipscanner.core.self_update.verify_deb", side_effect=UpdateVerificationError("not ours")
    ), patch("simple_ipscanner.core.self_update.subprocess.Popen") as mock_popen:
        with pytest.raises(UpdateVerificationError):
            launch_installer("/tmp/evil.deb", expected_version="v1.2.3")

    mock_popen.assert_not_called()


def test_launch_installer_linux_falls_back_to_xdg_open_without_pkexec_or_apt():
    with patch("simple_ipscanner.core.self_update.sys.platform", "linux"), patch(
        "simple_ipscanner.core.self_update.shutil.which", return_value=None
    ), patch("simple_ipscanner.core.self_update.subprocess.Popen") as mock_popen:
        result = launch_installer("/tmp/simple-ipscanner_1.2.3_amd64.deb")

    mock_popen.assert_called_once_with(["xdg-open", "/tmp/simple-ipscanner_1.2.3_amd64.deb"])
    assert result is mock_popen.return_value


def test_launch_installer_macos_uses_open():
    with patch("simple_ipscanner.core.self_update.sys.platform", "darwin"), patch(
        "simple_ipscanner.core.self_update.subprocess.Popen"
    ) as mock_popen:
        result = launch_installer("/tmp/Simple-IPScanner.dmg")

    # `open` mounts the dmg and opens a Finder window for it, but that
    # window doesn't reliably come to the front on its own — right
    # before this app quits, that looks exactly like nothing happened.
    assert mock_popen.call_args_list[0].args[0] == ["open", "/tmp/Simple-IPScanner.dmg"]
    assert mock_popen.call_args_list[1].args[0] == ["open", "-a", "Finder"]
    assert result is mock_popen.return_value


def test_launch_installer_macos_still_returns_the_process_if_raising_finder_fails():
    def fake_popen(args, **kwargs):
        if args == ["open", "-a", "Finder"]:
            raise OSError("no Finder?")
        return "mock-dmg-process"

    with patch("simple_ipscanner.core.self_update.sys.platform", "darwin"), patch(
        "simple_ipscanner.core.self_update.subprocess.Popen", side_effect=fake_popen
    ):
        result = launch_installer("/tmp/Simple-IPScanner.dmg")

    assert result == "mock-dmg-process"


def test_launch_installer_windows_uses_startfile():
    with patch("simple_ipscanner.core.self_update.sys.platform", "win32"), patch(
        "os.startfile", create=True
    ) as mock_startfile:
        result = launch_installer("C:\\temp\\Setup.exe")

    mock_startfile.assert_called_once_with("C:\\temp\\Setup.exe")
    # No process handle for os.startfile — main_window.py falls back to a
    # timed quit instead of waiting on a process.
    assert result is None
