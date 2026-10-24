import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ratchet.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ratchet", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ratchet = load()


@pytest.mark.parametrize(
    ("row", "gate"),
    [
        ("| Project coverage | 100.00% (2026-10-24, Task 3) | must not fall |", 99.5),
        ("| Project coverage | at least 92.4% | must not fall |", 91.9),
        ("| Project coverage | 80.0% | must not fall |", 85.0),  # never below the floor
        ("| Project coverage | not measured yet | must not fall |", 85.0),
    ],
)
def test_gate_is_the_recorded_value_minus_half_a_point_but_not_below_85(
    tmp_path: Path, row: str, gate: float
) -> None:
    constraints = tmp_path / "CONSTRAINTS.md"
    constraints.write_text(f"# Constraints\n\n{row}\n", encoding="utf-8")

    assert ratchet.coverage_gate(constraints) == pytest.approx(gate)


def test_script_prints_the_gate_for_the_repository() -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=SCRIPT.parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert float(result.stdout) >= 85.0


def test_script_fails_without_the_file(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "missing.md")],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
