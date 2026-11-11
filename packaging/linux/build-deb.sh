#!/usr/bin/env bash
# Packages dist/Simple-IPScanner/ (already built by PyInstaller, onedir mode)
# into a .deb that installs to /opt/simple-ipscanner and adds a proper menu
# entry + icon, so it behaves like a native app rather than a dropped
# binary. Uses dpkg-deb directly, which ships with Debian-based distros
# (Pop!_OS included) — no extra tool to install in CI.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUNDLE="$ROOT/dist/Simple-IPScanner"
VERSION="$(grep -o '__version__ = "[^"]*"' "$ROOT/src/simple_ipscanner/__init__.py" | cut -d'"' -f2)"
ARCH="$(dpkg --print-architecture)"
PKG_ROOT="$ROOT/dist/deb-staging"
OUT="$ROOT/dist/simple-ipscanner_${VERSION}_${ARCH}.deb"

if [ ! -d "$BUNDLE" ]; then
  echo "error: $BUNDLE not found — run PyInstaller first" >&2
  exit 1
fi

rm -rf "$PKG_ROOT" "$OUT"
mkdir -p "$PKG_ROOT/DEBIAN"
mkdir -p "$PKG_ROOT/opt/simple-ipscanner"
mkdir -p "$PKG_ROOT/usr/bin"
mkdir -p "$PKG_ROOT/usr/share/applications"

cp -R "$BUNDLE"/. "$PKG_ROOT/opt/simple-ipscanner/"
ln -s /opt/simple-ipscanner/Simple-IPScanner "$PKG_ROOT/usr/bin/simple-ipscanner"
cp "$ROOT/packaging/linux/simple-ipscanner.desktop" "$PKG_ROOT/usr/share/applications/"

for size in 16 32 48 64 128 256 512; do
  dir="$PKG_ROOT/usr/share/icons/hicolor/${size}x${size}/apps"
  mkdir -p "$dir"
  cp "$ROOT/packaging/icons/icon_${size}.png" "$dir/simple-ipscanner.png"
done

cat > "$PKG_ROOT/DEBIAN/control" <<EOF
Package: simple-ipscanner
Version: $VERSION
Section: misc
Priority: optional
Architecture: $ARCH
Depends: libegl1, libxkbcommon0, libxcb-cursor0, libfontconfig1, libdbus-1-3, iputils-ping
Maintainer: Mike Hellyer
Description: Find the devices on your network, like Angry IP Scanner
 Scans an IP range for live devices and shows their ping time, hostname,
 MAC address, maker and open ports. Ping any device by hand, have it beep
 when a device goes offline or comes online, and see which devices have
 been switched off since the last scan.
EOF

dpkg-deb --build --root-owner-group "$PKG_ROOT" "$OUT"
rm -rf "$PKG_ROOT"

echo "wrote $OUT"
