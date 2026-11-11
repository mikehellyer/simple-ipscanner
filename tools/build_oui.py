"""One-off script: turns the IEEE's MAC address block list into the small
table the app looks makers up in (core/data/oui.tsv.gz). Re-run now and
then to pick up newly registered makers.

Usage: venv/bin/python tools/build_oui.py path/to/oui.csv
(download oui.csv from https://standards-oui.ieee.org/oui/oui.csv)
"""
from __future__ import annotations

import csv
import gzip
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "src" / "simple_ipscanner" / "core" / "data" / "oui.tsv.gz"


def main(source: str) -> None:
    rows = {}
    with open(source, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            prefix = row["Assignment"].strip().upper()
            name = " ".join(row["Organization Name"].split())
            if len(prefix) == 6 and name:
                rows[prefix] = name
    text = "".join(f"{p}\t{n}\n" for p, n in sorted(rows.items()))
    with gzip.open(OUT, "wt", encoding="utf-8", compresslevel=9) as out:
        out.write(text)
    print(f"wrote {len(rows)} makers to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1])
