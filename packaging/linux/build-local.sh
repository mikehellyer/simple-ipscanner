#!/usr/bin/env bash
# Builds an installable .deb on this machine, with a new version number
# every time: bumps the last part of the version (0.1.0 -> 0.1.1), runs
# the tests, freezes the app with PyInstaller, self-tests the result,
# packages it, and commits the new version number.
#
# Usage: bash packaging/linux/build-local.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
PY="$ROOT/venv/bin/python"

OLD="$(grep -o '__version__ = "[^"]*"' src/simple_ipscanner/__init__.py | cut -d'"' -f2)"
NEW="$("$PY" -c "v='$OLD'.split('.'); v[-1]=str(int(v[-1])+1); print('.'.join(v))")"

echo "== testing"
"$ROOT/venv/bin/pytest" -q

echo "== version $OLD -> $NEW"
sed -i "s/__version__ = \"$OLD\"/__version__ = \"$NEW\"/" src/simple_ipscanner/__init__.py
sed -i "s/^version = \"$OLD\"/version = \"$NEW\"/" pyproject.toml

echo "== building"
rm -rf build dist
"$ROOT/venv/bin/pyinstaller" --noconfirm --log-level WARN packaging/pyinstaller/simple-ipscanner.spec
dist/Simple-IPScanner/Simple-IPScanner --self-test
bash packaging/linux/build-deb.sh

git add src/simple_ipscanner/__init__.py pyproject.toml
git -c user.name="Mike Hellyer" -c user.email=mikehellyer@gmail.com commit -q -m "Bump to v$NEW"

echo
echo "Built dist/simple-ipscanner_${NEW}_$(dpkg --print-architecture).deb — install it with:"
echo "  sudo apt install $ROOT/dist/simple-ipscanner_${NEW}_$(dpkg --print-architecture).deb"
