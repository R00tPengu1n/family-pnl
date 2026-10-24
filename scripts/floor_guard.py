"""Diff-scoped enforcement of the CONSTRAINTS.md floor.

Detects moves that lower the bar between the merge base and the working tree:
a silenced checker, a test made easier or deleted, an assertion removed,
unfinished work, a new exception, and a weakened or removed rule in CONSTRAINTS.md.

Usage: python scripts/floor_guard.py [--base <ref>]   (default base: origin/main)
Exit codes: 0 clean, 1 floor violation, 2 the guard could not run.

Standard library only, so it runs before the project environment exists.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CONSTRAINTS = "CONSTRAINTS.md"
# Files that quote the patterns below by design.
SELF_EXEMPT = {"scripts/floor_guard.py", "tests/scripts/test_floor_guard.py", CONSTRAINTS}

SUPPRESSIONS = re.compile(
    r"#\s*noqa|#\s*type:\s*ignore|#\s*pyright:\s*ignore|#\s*pragma:\s*no\s*cover"
    r"|#\s*nosec|nosemgrep|gitleaks:allow|pragma:\s*no\s*mutate|#\s*lint-imports:\s*ignore"
)
STUBS = re.compile(r"raise\s+NotImplementedError|\bTODO\b|\bFIXME\b|except\b[^:]*:\s*pass\b")
SKIPS = re.compile(
    r"pytest\.mark\.(skip|skipif|xfail)\b|\bpytest\.skip\(|\bunittest\.skip|\.skipTest\("
)
ASSERTIONS = re.compile(r"\bassert\b|pytest\.raises|pytest\.warns|\.assert_\w+\(")
EXCEPTION_ROW = re.compile(r"^\|\s*W\d+\s*\|")
EXCEPTION_REF = re.compile(r"\bW\d+\b")

MIN_BEFORE = re.compile(r"(>=|>|≥|at least|minimum|\bmin\b|no less than|not fall|not drop)\s*$")
MAX_BEFORE = re.compile(
    r"(<=|<|≤|at most|maximum|\bmax\b|no more than|under|below|not grow|not exceed)\s*$"
)
MIN_AFTER = re.compile(r"^\s*\S*\s*(or more|or higher|must not fall|must not drop)")
MAX_AFTER = re.compile(r"^\s*\S*\s*(or less|or lower|must not grow|must not exceed)")


@dataclass(frozen=True, slots=True)
class Line:
    file: str
    text: str


@dataclass(frozen=True, slots=True)
class Finding:
    rule: str
    file: str
    text: str


class GuardError(Exception):
    """The guard could not run; never reported as clean."""


def git(*args: str, diff_exit: bool = False) -> str:
    result = subprocess.run(
        ["git", *args], capture_output=True, encoding="utf-8", errors="replace", check=False
    )
    # `git diff --no-index` exits 1 whenever the sides differ, which is normal for a new file.
    if result.returncode == 0 or (diff_exit and result.returncode == 1):
        return result.stdout
    raise GuardError(f"git {' '.join(args)} failed: {result.stderr.strip()}")


def collect_diff(base: str) -> str:
    merge_base = git("merge-base", base, "HEAD").strip()
    if not merge_base:
        raise GuardError(f"no merge base against {base}")
    tracked = git("diff", "--unified=0", merge_base, "--")
    untracked = [
        git("diff", "--no-index", "--unified=0", "/dev/null", name, diff_exit=True)
        for name in git("ls-files", "--others", "--exclude-standard").splitlines()
        if name
    ]
    return "\n".join([tracked, *untracked])


def parse_diff(diff: str) -> tuple[list[Line], list[Line], list[str]]:
    added: list[Line] = []
    removed: list[Line] = []
    deleted: list[str] = []
    file = old_file = ""
    in_header = False
    for raw in diff.split("\n"):
        line = raw.rstrip("\r")
        if line.startswith("diff "):
            in_header = True
        elif line.startswith("@@"):
            in_header = False
        elif in_header:
            # `---` / `+++` are headers only before the first hunk of a file.
            if line.startswith("--- "):
                old_file = re.sub(r"^[ab]/", "", line[4:])
            elif line.startswith("+++ "):
                new_file = re.sub(r"^[ab]/", "", line[4:])
                file = old_file if new_file == "/dev/null" else new_file
                if new_file == "/dev/null":
                    deleted.append(file)
        elif line.startswith("+"):
            added.append(Line(file, line[1:]))
        elif line.startswith("-"):
            removed.append(Line(file, line[1:]))
    return added, removed, deleted


def is_test(path: str) -> bool:
    name = Path(path).name
    return path.startswith("tests/") or name.startswith("test_") or name.endswith("_test.py")


def rule_key(text: str) -> str | None:
    s = text.strip()
    if s.startswith("|"):
        cells = [c.strip() for c in s.split("|") if c.strip()]
        return cells[0] if cells else ""
    if s.startswith(("- ", "* ")):
        return s[2:].split(":")[0].strip()
    return None  # prose, headings, dates: not a rule


def thresholds(text: str) -> list[tuple[float, str | None]]:
    found: list[tuple[float, str | None]] = []
    for match in re.finditer(r"\d+(?:\.\d+)?", text):
        before = text[max(0, match.start() - 24) : match.start()].lower()
        after = text[match.end() : match.end() + 40].lower()
        if MIN_BEFORE.search(before) or MIN_AFTER.search(after):
            direction: str | None = "min"
        elif MAX_BEFORE.search(before) or MAX_AFTER.search(after):
            direction = "max"
        else:
            direction = None
        found.append((float(match.group()), direction))
    return found


def compare_rule(was: str, now: str) -> str | None:
    before, after = thresholds(was), thresholds(now)
    for direction in ("min", "max", None):
        old = [n for n, d in before if d == direction]
        new = [n for n, d in after if d == direction]
        for i, value in enumerate(old):
            if i >= len(new):
                return "threshold-removed"
            if new[i] == value:
                continue
            if direction is None:
                return "threshold-changed"
            if (direction == "min" and new[i] < value) or (direction == "max" and new[i] > value):
                return "threshold-loosened"
    return None


def known_exceptions() -> set[str]:
    path = Path(CONSTRAINTS)
    if not path.exists():
        return set()
    return {
        m.group().strip("| ")
        for line in path.read_text(encoding="utf-8").splitlines()
        if (m := EXCEPTION_ROW.match(line.strip()))
    }


def check(added: list[Line], removed: list[Line], deleted: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    exceptions = known_exceptions()

    def flag(rule: str, file: str, text: str) -> None:
        findings.append(Finding(rule, file, text.strip()[:120]))

    for line in added:
        if line.file == CONSTRAINTS and EXCEPTION_ROW.match(line.text.strip()):
            flag("new-exception", line.file, line.text)
        if line.file in SELF_EXEMPT:
            continue
        if SUPPRESSIONS.search(line.text):
            # A suppression is allowed only when it cites a tracked exception id.
            refs = set(EXCEPTION_REF.findall(line.text))
            if not refs or not refs <= exceptions:
                flag("silenced-checker", line.file, line.text)
        if STUBS.search(line.text):
            flag("unfinished-work", line.file, line.text)
        if SKIPS.search(line.text):
            flag("test-made-easier", line.file, line.text)

    for path in deleted:
        if is_test(path):
            flag("test-deleted", path, "file deleted")
    for line in removed:
        if is_test(line.file) and line.file not in deleted and ASSERTIONS.search(line.text):
            flag("assertion-removed", line.file, line.text)

    removed_rules = [r for r in removed if r.file == CONSTRAINTS and rule_key(r.text)]
    added_rules = [a for a in added if a.file == CONSTRAINTS and rule_key(a.text)]
    for old in removed_rules:
        new = next((a for a in added_rules if rule_key(a.text) == rule_key(old.text)), None)
        if new is None:
            # Dropping an exception tightens the bar: silent.
            if not EXCEPTION_ROW.match(old.text.strip()):
                flag("rule-removed", old.file, old.text)
            continue
        verdict = compare_rule(old.text, new.text)
        if verdict:
            flag(verdict, old.file, f"{old.text.strip()}  ->  {new.text.strip()}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main")
    args = parser.parse_args()
    # Windows consoles default to a legacy code page; CONSTRAINTS.md contains ≥ and ≤.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        top = git("rev-parse", "--show-toplevel").strip()
        if not top:
            raise GuardError("not inside a git work tree")
        # `git ls-files` is relative to the current directory; run from the top.
        os.chdir(top)
        findings = check(*parse_diff(collect_diff(args.base)))
    except GuardError as exc:
        print(f"floor-guard: {exc}", file=sys.stderr)
        return 2

    if not findings:
        print("floor-guard: clean")
        return 0
    print(f"floor-guard: {len(findings)} floor violation(s):", file=sys.stderr)
    for f in findings:
        print(f"  [{f.rule}] {f.file}: {f.text}", file=sys.stderr)
    if any(f.rule == "rule-removed" for f in findings):
        print(
            "\nA rule-removed finding can also mean the rule's label changed: rename a rule "
            "in one commit and change its thresholds in another.",
            file=sys.stderr,
        )
    print(
        "\nEach is a move that lowers the bar. Fix the code, or route it through a tracked "
        "exception (CONSTRAINTS.md, Exceptions).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
