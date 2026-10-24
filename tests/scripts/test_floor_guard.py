"""Tests for scripts/floor_guard.py: a broken guard would silently pass every violation."""

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "floor_guard.py"


def load_guard() -> ModuleType:
    spec = importlib.util.spec_from_file_location("floor_guard", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["floor_guard"] = module
    spec.loader.exec_module(module)
    return module


guard = load_guard()
Line = guard.Line


def rules(findings: list[Any]) -> list[str]:
    return [f.rule for f in findings]


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # check() reads CONSTRAINTS.md from the current directory for known exception ids.
    monkeypatch.chdir(tmp_path)


@pytest.mark.parametrize(
    "text",
    [
        "x = f()  # noqa: E501",
        "y: int = g()  # type: ignore[assignment]",
        "if debug:  # pragma: no cover",
        "run(cmd)  # nosec",
        "eval(x)  # nosemgrep",
    ],
)
def test_new_suppression_comment_is_flagged(text: str) -> None:
    findings = guard.check([Line("src/a.py", text)], [], [])

    assert rules(findings) == ["silenced-checker"]


def test_suppression_citing_a_tracked_exception_is_allowed(tmp_path: Path) -> None:
    (tmp_path / "CONSTRAINTS.md").write_text(
        "| W1 | type | src/a.py | untyped lib | @owner | 2027-01-01 |\n", encoding="utf-8"
    )

    findings = guard.check([Line("src/a.py", "import lib  # type: ignore  # W1")], [], [])

    assert findings == []


def test_suppression_citing_an_unknown_exception_is_flagged() -> None:
    findings = guard.check([Line("src/a.py", "import lib  # type: ignore  # W9")], [], [])

    assert rules(findings) == ["silenced-checker"]


@pytest.mark.parametrize(
    "text",
    ["    raise NotImplementedError", "# TODO: handle errors", "except ValueError: pass"],
)
def test_unfinished_work_is_flagged(text: str) -> None:
    assert rules(guard.check([Line("src/a.py", text)], [], [])) == ["unfinished-work"]


@pytest.mark.parametrize(
    "text", ["@pytest.mark.skip", "@pytest.mark.xfail(reason='flaky')", "    pytest.skip('later')"]
)
def test_skipped_test_is_flagged(text: str) -> None:
    assert rules(guard.check([Line("tests/test_a.py", text)], [], [])) == ["test-made-easier"]


def test_deleted_test_file_is_flagged() -> None:
    assert rules(guard.check([], [], ["tests/unit/test_money.py"])) == ["test-deleted"]


def test_assertion_removed_from_a_remaining_test_is_flagged() -> None:
    removed = [Line("tests/unit/test_money.py", "    assert total == Decimal('3.00')")]

    assert rules(guard.check([], removed, [])) == ["assertion-removed"]


def test_assertion_rewritten_in_place_is_not_a_removal() -> None:
    removed = [Line("tests/test_health.py", '    assert response.json() == {"status": "ok"}')]
    added = [
        Line("tests/test_health.py", '    assert response.json() == {"status": "ok", "db": "ok"}')
    ]

    assert guard.check(added, removed, []) == []


def test_fewer_assertions_in_a_test_file_is_flagged() -> None:
    removed = [
        Line("tests/test_a.py", "    assert a == 1"),
        Line("tests/test_a.py", "    assert b == 2"),
    ]
    added = [Line("tests/test_a.py", "    assert a == 1 and b == 2")]

    assert rules(guard.check(added, removed, [])) == ["assertion-removed"]


def test_assertion_removed_from_source_code_is_not_a_test_change() -> None:
    assert guard.check([], [Line("src/a.py", "    assert x")], []) == []


def test_lowered_minimum_threshold_is_flagged() -> None:
    removed = [Line("CONSTRAINTS.md", "| Coverage (project) | ≥ 85% of lines |")]
    added = [Line("CONSTRAINTS.md", "| Coverage (project) | ≥ 80% of lines |")]

    assert rules(guard.check(added, removed, [])) == ["threshold-loosened"]


def test_raised_maximum_threshold_is_flagged() -> None:
    removed = [Line("CONSTRAINTS.md", "| Edit-loop budget | Fast check ≤ 10 s |")]
    added = [Line("CONSTRAINTS.md", "| Edit-loop budget | Fast check ≤ 30 s |")]

    assert rules(guard.check(added, removed, [])) == ["threshold-loosened"]


def test_tightened_threshold_is_silent() -> None:
    removed = [Line("CONSTRAINTS.md", "| Coverage (project) | ≥ 85% of lines |")]
    added = [Line("CONSTRAINTS.md", "| Coverage (project) | ≥ 90% of lines |")]

    assert guard.check(added, removed, []) == []


def test_threshold_dropped_from_a_rule_is_flagged() -> None:
    removed = [Line("CONSTRAINTS.md", "| Coverage (project) | ≥ 85% | `pytest --cov` |")]
    added = [Line("CONSTRAINTS.md", "| Coverage (project) | see pyproject | `pytest --cov` |")]

    assert rules(guard.check(added, removed, [])) == ["threshold-removed"]


def test_removed_rule_is_flagged() -> None:
    removed = [Line("CONSTRAINTS.md", "| Lint | Zero ruff errors |")]

    assert rules(guard.check([], removed, [])) == ["rule-removed"]


def test_new_exception_row_is_flagged_and_removing_one_is_silent() -> None:
    row = "| W2 | noqa | src/b.py | reason | @owner | 2027-01-01 |"

    assert rules(guard.check([Line("CONSTRAINTS.md", row)], [], [])) == ["new-exception"]
    assert guard.check([], [Line("CONSTRAINTS.md", row)], []) == []


def test_parse_diff_tracks_files_additions_removals_and_deletions() -> None:
    diff = "\n".join(
        [
            "diff --git a/src/a.py b/src/a.py",
            "--- a/src/a.py",
            "+++ b/src/a.py",
            "@@ -1 +1 @@",
            "-old = 1",
            "+new = 2",
            "+++counter",  # inside a hunk this is content, not a header
            "diff --git a/tests/test_b.py b/tests/test_b.py",
            "--- a/tests/test_b.py",
            "+++ /dev/null",
            "@@ -1 +0,0 @@",
            "-def test_b(): ...",
        ]
    )

    added, removed, deleted = guard.parse_diff(diff)

    assert added == [Line("src/a.py", "new = 2"), Line("src/a.py", "++counter")]
    assert removed == [Line("src/a.py", "old = 1"), Line("tests/test_b.py", "def test_b(): ...")]
    assert deleted == ["tests/test_b.py"]


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def run_guard(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "guard@example.com")
    git(path, "config", "user.name", "guard")
    git(path, "config", "core.autocrlf", "false")
    (path / "app.py").write_text("x = 1\n", encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "base")
    return path


def test_script_exits_0_on_a_clean_diff(repo: Path) -> None:
    (repo / "app.py").write_text("x = 2\n", encoding="utf-8")

    result = run_guard(repo, "--base", "main")

    assert result.returncode == 0
    assert "clean" in result.stdout


def test_script_exits_1_and_sees_untracked_files(repo: Path) -> None:
    (repo / "new.py").write_text("y = 1  # noqa\n", encoding="utf-8")

    result = run_guard(repo, "--base", "main")

    assert result.returncode == 1
    assert "[silenced-checker] new.py" in result.stderr


def test_script_exits_2_when_the_base_is_missing(repo: Path) -> None:
    result = run_guard(repo, "--base", "no-such-ref")

    assert result.returncode == 2
