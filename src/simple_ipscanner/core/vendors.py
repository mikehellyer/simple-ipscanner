"""Who made a device, from the first half of its MAC address (the IEEE's
list, bundled — tools/build_oui.py refreshes it)."""
from __future__ import annotations

import gzip
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data" / "oui.tsv.gz"


@lru_cache(maxsize=1)
def _table() -> dict[str, str]:
    try:
        with gzip.open(DATA, "rt", encoding="utf-8") as f:
            return dict(line.rstrip("\n").split("\t", 1) for line in f if "\t" in line)
    except OSError:
        return {}


def vendor_for(mac: str) -> str:
    prefix = mac.replace(":", "").replace("-", "").upper()[:6]
    if len(prefix) < 6:
        return ""
    if int(prefix[1], 16) & 2:
        # The "locally administered" bit: a made-up address, as phones use
        # for privacy on Wi-Fi, so no maker can be known.
        return "(private address)"
    return _table().get(prefix, "")
