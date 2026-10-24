# Constraints

The quality bar for Family P&L. Every check blocks: a red check means the task is not
done and nothing is committed. Read this before writing code and never weaken it to make
a change pass. Changes to this file go in their own commit and PR.

Last reviewed: 2026-10-24 by @R00tPengu1n

## Floor (always enforced)

Checked by `python scripts/floor_guard.py` on the diff against `origin/main`
(exit 0 clean, 1 violation, 2 could not run — 2 is never treated as clean).

- No new suppression comments: `# noqa`, `# type: ignore`, `# pragma: no cover`, `# nosec`,
  `nosemgrep`, `gitleaks:allow`, `pragma: no mutate` — unless the same line cites a tracked
  exception id (`# type: ignore[import-untyped]  # W1`)
- No unfinished work: `raise NotImplementedError`, `except ...: pass`, `TODO`, `FIXME`
- No skipped, xfailed or deleted tests and no assertions removed from tests that stay
- No secrets in source; `.env` is never committed
- No `float` for money; business code takes time from the injected `Clock`
- This file is not weakened to make a change pass: lowered thresholds, removed rules and new
  exceptions are reported by the floor guard

## Enforced with numbers

| Dimension | Rule | Checked by | Runs at | Why this number |
|---|---|---|---|---|
| Lint | Zero ruff errors, format clean | `uv run ruff check .` and `uv run ruff format --check .` | edit, task end, CI | Style is not discussed in review |
| Types | Zero mypy errors in strict mode | `uv run python -m mypy` | edit, task end, CI | Strict typing is part of the spec |
| Layers | Zero import-linter contract violations | `uv run lint-imports` (`check.ps1` calls `importlinter.cli` through python) | edit, task end, CI | Enforces the dependency direction from `SPEC.md` (see contracts below) |
| Floor | Zero floor guard findings | `python scripts/floor_guard.py` | edit, task end, CI | See Floor |
| Secrets | Zero gitleaks findings | `gitleaks git --redact --no-banner` | CI (locally `.env` is git-ignored) | Any leaked token is an incident; `--redact` keeps values out of logs |
| Tests | All tests pass, none skipped | `uv run python -m pytest` | task end, CI | Red tests mean the task is not done |
| Coverage (project) | ≥ 85% of `src/` lines and branches | `uv run python -m pytest --cov --cov-fail-under=85` (branch coverage on in `pyproject.toml`) | task end, CI | Spec success criterion |
| Security: code | Zero findings at ERROR severity | `semgrep scan --config p/python --config p/owasp-top-ten --severity ERROR --error src` | CI | External opinion on injection, crypto and auth mistakes; WARNING findings are reviewed, not blocking |
| Security: deps | No known vulnerability in locked dependencies | `uv export --frozen --no-emit-project` then `pip-audit -r <file> --strict --require-hashes --disable-pip` | CI | External vulnerability database; required by the spec |
| Mutation score | ≥ 60% killed mutants in `src/family_pnl/domain/` | `mutmut run` on changed domain modules, score from `mutmut export-cicd-stats` | CI, PRs touching `domain/` | Starting value for a suite never mutated before; raised by ratchet |
| Task-end budget | Full local check ≤ 90 s | `.\scripts\check.ps1 -Stage task` | task end | Owner's limit; slower checks move to CI |
| Edit-loop budget | Fast check ≤ 10 s | `.\scripts\check.ps1 -Stage fast` | after edits | A slow edit loop gets skipped |
| Exception lifetime | ≤ 90 days | review of the Exceptions table | review | Long enough to plan a fix, short enough to remember |

### Import-linter contracts

Configured in `pyproject.toml` (`[tool.importlinter]`):

1. Layers: `family_pnl.api` → `family_pnl.services` → `family_pnl.repositories` →
   `family_pnl.models`; lower layers never import higher ones.
2. `family_pnl.domain` imports nothing from `fastapi`, `sqlalchemy`, `httpx`, `redis`, `arq`
   or other `family_pnl` packages except `family_pnl.core`.
3. `family_pnl_bot` never imports `family_pnl`.
4. `family_pnl.worker` and `family_pnl.api` do not import each other.

## Stages

On Windows with Smart App Control the unsigned `.exe` wrappers of Python tools are
blocked, so `check.ps1` runs every tool as `python -m <tool>` from `.venv`.

| Stage | Command | What runs | Budget |
|---|---|---|---|
| fast | `.\scripts\check.ps1 -Stage fast` | ruff check, ruff format check, mypy, lint-imports, floor guard | ≤ 10 s |
| task | `.\scripts\check.ps1 -Stage task` | fast + pytest with coverage gate | ≤ 90 s |
| full | `.\scripts\check.ps1 -Stage full` | task + pip-audit (Semgrep, gitleaks and mutmut run in CI on Linux: their Windows support is limited) | minutes |
| CI | `.github/workflows/ci.yml` | full + Semgrep + gitleaks + mutmut + Docker build | minutes |

`.\scripts\check.ps1` with no argument runs `task` and writes `.reports/check.log`.

## Measured, not yet enforced

Each value must not fall by more than 0.5 percentage points; when it improves, the new
value is recorded here.

| Metric | Today | Direction |
|---|---|---|
| Project coverage | 100.00% (2026-10-24, Task 3) | must not fall |
| Mutation score (domain) | not measured yet: first domain code arrives in Task 9 | must not fall |

## Exceptions

A suppression comment is allowed only when it cites an id from this table.

| ID | Rule | Path | Reason | Owner | Expires |
|---|---|---|---|---|---|
