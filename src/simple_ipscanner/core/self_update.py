"""Downloading and launching an update, once the user has asked for it.

Simple-IPScanner never does this on its own — check_for_update() only ever
notifies. Everything here only runs after an explicit "Update" click.

The installer ends up running with the user's (or, on Linux, root's)
privileges, so it's checked on the way: the link has to point at this
app's own GitHub releases, the download has to actually come from
GitHub, and on Linux the .deb has to really be the simple-ipscanner
package at the expected version before it's handed to pkexec/apt.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from simple_ipscanner.core.http import MAX_INSTALLER_BYTES, ResponseTooLargeError, urlopen

DOWNLOAD_TIMEOUT_SECONDS = 30
DEB_PACKAGE_NAME = "simple-ipscanner"
# A release asset link is on github.com, which redirects to GitHub's own
# download servers on *.githubusercontent.com.
_DOWNLOAD_HOSTS = ("github.com",)
_DOWNLOAD_HOST_SUFFIXES = (".githubusercontent.com",)


class UpdateVerificationError(OSError):
    """The download isn't the installer it should be, so it won't be run."""


def release_download_prefix(owner: str, repo: str) -> str:
    return f"https://github.com/{owner}/{repo}/releases/download/"


def _is_github_download(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        host in _DOWNLOAD_HOSTS or host.endswith(_DOWNLOAD_HOST_SUFFIXES)
    )


def _installer_suffix() -> str:
    if sys.platform == "win32":
        return ".exe"
    if sys.platform == "darwin":
        return ".dmg"
    return ".deb"


def find_asset_for_this_platform(
    assets: list[tuple[str, str]], owner: str, repo: str
) -> Optional[str]:
    """Return the download URL of the release asset built for this OS, if
    any — only ever a link into owner/repo's own GitHub releases.
    """
    suffix = _installer_suffix()
    prefix = release_download_prefix(owner, repo)
    for name, download_url in assets:
        if name.lower().endswith(suffix) and download_url.startswith(prefix):
            return download_url
    return None


def download_asset(url: str) -> Optional[Path]:
    """Download a release asset to a fresh, private temp directory. None on
    failure — including a download that didn't come from GitHub or is
    implausibly large.
    """
    # A fixed name, rather than whatever the link ends in.
    dest_dir = Path(tempfile.mkdtemp(prefix="simple-ipscanner-update-"))
    dest_path = dest_dir / f"simple-ipscanner-update{_installer_suffix()}"

    request = urllib.request.Request(url, headers={"User-Agent": "Simple-IPScanner/1"})
    try:
        if not _is_github_download(url):
            raise UpdateVerificationError(f"not a GitHub download: {url}")
        with urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
            if not _is_github_download(response.geturl()):
                raise UpdateVerificationError(f"redirected away from GitHub: {response.geturl()}")
            written = 0
            with open(dest_path, "wb") as out_file:
                while chunk := response.read(1024 * 1024):
                    written += len(chunk)
                    if written > MAX_INSTALLER_BYTES:
                        raise ResponseTooLargeError("installer download is implausibly large")
                    out_file.write(chunk)
    except OSError:
        shutil.rmtree(dest_dir, ignore_errors=True)
        return None
    return dest_path


def verify_deb(path: Path | str, expected_version: Optional[str]) -> None:
    """Raise UpdateVerificationError unless the .deb at `path` is the
    simple-ipscanner package (at `expected_version`, a release tag like
    "v0.11.21", if given). Run before it's installed as root.
    """
    dpkg_deb = shutil.which("dpkg-deb")
    if dpkg_deb is None:
        raise UpdateVerificationError("dpkg-deb isn't available to check the update")
    try:
        result = subprocess.run(
            [dpkg_deb, "--field", str(path), "Package", "Version"],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise UpdateVerificationError("checking the update took too long") from exc
    fields = dict(
        line.split(": ", 1) for line in result.stdout.splitlines() if ": " in line
    )
    if result.returncode != 0 or fields.get("Package") != DEB_PACKAGE_NAME:
        raise UpdateVerificationError("the downloaded file isn't the Simple-IPScanner package")
    if expected_version and fields.get("Version") != expected_version.lstrip("vV"):
        raise UpdateVerificationError(
            f"the downloaded package is version {fields.get('Version')}, "
            f"not {expected_version.lstrip('vV')}"
        )


def launch_installer(path: Path, expected_version: Optional[str] = None) -> Optional[subprocess.Popen]:
    """Hand the downloaded installer off to the OS's normal action for it
    (runs the .exe, mounts the .dmg, installs the .deb). Raises OSError
    if nothing could be launched at all — the caller decides how to tell
    the user. UpdateVerificationError (an OSError) means the download
    failed its checks and nothing was launched.

    Returns the spawned process where there is one, so a caller on Linux
    can wait for it to finish before quitting — quitting immediately
    there can kill the pkexec authentication prompt before it's
    answered, since the desktop session ties a launched app's child
    processes to its own lifetime. Windows has no equivalent handle for
    os.startfile, hence None there even on success.
    """
    path = str(path)
    if sys.platform == "win32":
        import os

        os.startfile(path)
        return None
    elif sys.platform == "darwin":
        process = subprocess.Popen(["open", path])
        # `open` on a .dmg mounts it and opens a Finder window for it,
        # but that window doesn't reliably become frontmost on its own —
        # Finder can stay in the background, which (right before this
        # app quits a moment later) looks exactly like clicking Update
        # did nothing. Nudging Finder forward is harmless if it's
        # already there, and costs nothing if this fails.
        try:
            subprocess.Popen(["open", "-a", "Finder"])
        except OSError:
            pass
        return process
    else:
        # Handing a local .deb of an already-installed package to a
        # desktop "Software" GUI via xdg-open is unreliable across
        # distros: several (including GNOME Software / Pop!_Shop) show
        # an "Uninstall" action instead of "Install"/"Reinstall" for a
        # package already on the system, regardless of the downloaded
        # file's version — clicking it just removes the current install
        # and does nothing with the new file, forcing a separate manual
        # reinstall (and a second password prompt). Installing directly
        # via apt (through pkexec for a graphical privilege prompt)
        # upgrades in place with a single prompt instead.
        pkexec_path = shutil.which("pkexec")
        apt_path = shutil.which("apt")
        if pkexec_path and apt_path:
            # About to install as root: make sure it's really ours first.
            verify_deb(path, expected_version)
            # pkexec resolves the command it's given on its own, using a
            # restricted environment rather than the invoking shell's
            # $PATH — a bare "apt" can fail there (exit 127, "command
            # not found") even though `apt` works fine normally. Passing
            # the already-resolved absolute path sidesteps that.
            #
            # stderr is piped (not stdout — apt's stdout can be large,
            # and nothing reads it while this process is still running,
            # risking a full-pipe deadlock; stderr from a failed pkexec/
            # apt is always short) so a failure can show pkexec/apt's
            # actual error text instead of just a bare exit code — an
            # exit code alone hasn't been enough to diagnose this so far.
            return subprocess.Popen(
                [pkexec_path, apt_path, "install", "-y", path],
                stderr=subprocess.PIPE,
                text=True,
            )
        return subprocess.Popen(["xdg-open", path])
