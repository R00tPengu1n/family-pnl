"""Fail CI when the mutation score of the domain layer is below the CONSTRAINTS.md minimum.

Reads `mutants/mutmut-cicd-stats.json` written by `mutmut export-cicd-stats`.
Score = (killed + timeout) / (total - skipped), the same formula as `mutmut badge`;
mutants without covering tests count as not caught.

With --ratchet CONSTRAINTS.md the minimum is raised to the recorded score minus 0.5
percentage points ("must not fall", CONSTRAINTS.md, Measured).

Usage: python scripts/mutation_gate.py [--stats PATH] [--min PERCENT] [--ratchet PATH]
Exit codes: 0 at or above the minimum, 1 below it, 2 the gate could not run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DEFAULT_STATS = Path("mutants/mutmut-cicd-stats.json")
RATCHET_TOLERANCE = 0.5
_RECORDED = re.compile(r"^\|\s*Mutation score \(domain\)\s*\|\s*at least (\d+(?:\.\d+)?)%", re.M)


def score(stats: dict[str, int]) -> float:
    tested = stats.get("total", 0) - stats.get("skipped", 0)
    if tested <= 0:
        raise ValueError("no mutants were tested")
    caught = stats.get("killed", 0) + stats.get("timeout", 0)
    return caught / tested * 100


def recorded_score(constraints: Path) -> float:
    match = _RECORDED.search(constraints.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(f"no recorded mutation score in {constraints}")
    return float(match.group(1))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--stats", type=Path, default=DEFAULT_STATS)
    parser.add_argument("--min", type=float, default=60.0, dest="minimum")
    parser.add_argument("--ratchet", type=Path, help="CONSTRAINTS.md with the recorded score")
    args = parser.parse_args()

    try:
        stats = json.loads(args.stats.read_text(encoding="utf-8"))
        value = score(stats)
        minimum = args.minimum
        if args.ratchet is not None:
            minimum = max(minimum, recorded_score(args.ratchet) - RATCHET_TOLERANCE)
    except (OSError, ValueError) as exc:
        print(f"mutation-gate: cannot evaluate {args.stats}: {exc}", file=sys.stderr)
        return 2

    summary = (
        f"killed {stats.get('killed', 0)}, timeout {stats.get('timeout', 0)}, "
        f"survived {stats.get('survived', 0)}, no tests {stats.get('no_tests', 0)}"
    )
    if value < minimum:
        print(
            f"mutation-gate: score {value:.1f}% < {minimum:.1f}% ({summary})",
            file=sys.stderr,
        )
        return 1
    print(f"mutation-gate: score {value:.1f}% >= {minimum:.1f}% ({summary})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
