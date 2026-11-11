#!/usr/bin/env bash
# The security check every release has to pass (CI runs it before
# building installers; build-local.sh runs it before building a .deb):
#  - pip-audit: no known vulnerabilities in the packages that get bundled
#  - bandit: no medium- or high-severity problems in the app's own code
#
# Usage: bash packaging/security-check.sh [python]   (default: python)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${1:-python}"

echo "== dependency audit (pip-audit)"
"$PY" -m pip_audit --progress-spinner off -r "$ROOT/requirements.txt"

echo "== code scan (bandit, medium severity and up)"
"$PY" -m bandit -q -r "$ROOT/src" --severity-level medium --confidence-level medium

echo "security check passed"
