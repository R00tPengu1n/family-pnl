"""Tests for scripts/mutation_gate.py: the CI gate on the mutation score of the domain layer."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "mutation_gate.py"


def load_gate() -> ModuleType:
    spec = importlib.util.spec_from_file_location("mutation_gate", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load_gate()


def stats(**overrides: int) -> dict[str, int]:
    base = {"killed": 0, "survived": 0, "total": 0, "no_tests": 0, "skipped": 0, "timeout": 0}
    return base | overrides


def test_score_counts_killed_and_timed_out_mutants_as_caught() -> None:
    assert gate.score(stats(killed=6, timeout=1, survived=3, total=10)) == pytest.approx(70.0)


def test_mutants_without_tests_count_against_the_score() -> None:
    assert gate.score(stats(killed=5, no_tests=5, total=10)) == pytest.approx(50.0)


def test_skipped_mutants_are_excluded() -> None:
    assert gate.score(stats(killed=6, skipped=4, total=10)) == pytest.approx(100.0)


def test_no_tested_mutants_is_an_error() -> None:
    with pytest.raises(ValueError, match="no mutants"):
        gate.score(stats(skipped=3, total=3))


def run_gate(tmp_path: Path, content: str | None, *args: str) -> subprocess.CompletedProcess[str]:
    path = tmp_path / "mutmut-cicd-stats.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--stats", str(path), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_gate_passes_at_the_threshold(tmp_path: Path) -> None:
    result = run_gate(tmp_path, json.dumps(stats(killed=6, survived=4, total=10)), "--min", "60")

    assert result.returncode == 0
    assert "60.0%" in result.stdout


def test_gate_fails_below_the_threshold(tmp_path: Path) -> None:
    result = run_gate(tmp_path, json.dumps(stats(killed=5, survived=5, total=10)), "--min", "60")

    assert result.returncode == 1
    assert "50.0% < 60.0%" in result.stderr


def test_gate_cannot_run_without_stats(tmp_path: Path) -> None:
    assert run_gate(tmp_path, None).returncode == 2


def test_gate_cannot_run_on_malformed_stats(tmp_path: Path) -> None:
    assert run_gate(tmp_path, "{not json").returncode == 2


CONSTRAINTS_ROW = "| Mutation score (domain) | at least {value}% (Task 4) | must not fall |\n"


def test_ratchet_reads_the_recorded_score(tmp_path: Path) -> None:
    constraints = tmp_path / "CONSTRAINTS.md"
    constraints.write_text("# Constraints\n" + CONSTRAINTS_ROW.format(value="100.0"), "utf-8")

    assert gate.recorded_score(constraints) == pytest.approx(100.0)


def test_ratchet_without_a_recorded_score_is_an_error(tmp_path: Path) -> None:
    constraints = tmp_path / "CONSTRAINTS.md"
    constraints.write_text("| Mutation score (domain) | not measured yet | must not fall |\n")

    with pytest.raises(ValueError, match="recorded mutation score"):
        gate.recorded_score(constraints)


def test_gate_fails_when_the_score_falls_more_than_half_a_point(tmp_path: Path) -> None:
    constraints = tmp_path / "CONSTRAINTS.md"
    constraints.write_text(CONSTRAINTS_ROW.format(value="100.0"), encoding="utf-8")
    result = run_gate(
        tmp_path,
        json.dumps(stats(killed=62, survived=2, total=64)),
        "--min",
        "60",
        "--ratchet",
        str(constraints),
    )

    assert result.returncode == 1
    assert "96.9% < 99.5%" in result.stderr


def test_gate_tolerates_a_drop_of_half_a_point(tmp_path: Path) -> None:
    constraints = tmp_path / "CONSTRAINTS.md"
    constraints.write_text(CONSTRAINTS_ROW.format(value="90.0"), encoding="utf-8")
    result = run_gate(
        tmp_path,
        json.dumps(stats(killed=179, survived=21, total=200)),
        "--ratchet",
        str(constraints),
    )

    assert result.returncode == 0
