"""Print the coverage gate: the CONSTRAINTS.md floor or the ratchet, whichever is higher.

CONSTRAINTS.md records today's project coverage under "Measured"; it must not fall by more
than 0.5 percentage points. The fixed floor (85%) still applies when nothing is recorded.

Usage: pytest --cov --cov-fail-under="$(python scripts/ratchet.py)"
Exit code 2 when CONSTRAINTS.md cannot be read.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

FLOOR = 85.0
TOLERANCE = 0.5
_RECORDED = re.compile(r"^\|\s*Project coverage\s*\|\s*(?:at least )?(\d+(?:\.\d+)?)%", re.M)


def coverage_gate(constraints: Path) -> float:
    match = _RECORDED.search(constraints.read_text(encoding="utf-8"))
    if match is None:
        return FLOOR
    return max(FLOOR, float(match.group(1)) - TOLERANCE)


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("CONSTRAINTS.md")
    try:
        print(f"{coverage_gate(path):.1f}")
    except OSError as exc:
        print(f"ratchet: cannot read {path}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
