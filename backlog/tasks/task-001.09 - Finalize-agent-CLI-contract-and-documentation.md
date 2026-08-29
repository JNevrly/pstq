---
id: TASK-001.09
title: Finalize agent CLI contract and documentation
status: Done
assignee: []
created_date: '2026-08-28 07:21'
updated_date: '2026-08-29 15:01'
labels: []
dependencies:
  - TASK-001.05
  - TASK-001.06
  - TASK-001.07
  - TASK-001.08
references:
  - PST Search CLI — Implementation Brief.md
modified_files:
  - README.md
  - pstq/cli.py
  - tests/test_pstq.py
  - .opencode/skills/pstq/SKILL.md
parent_task_id: TASK-001
priority: medium
type: task
ordinal: 10000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Finalize the configured single-PST CLI interface, deterministic JSON schemas, error handling, limits, and operator documentation for AI-agent use.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Configuration documents one PST path, SQLite index path, and explicit data-directory behavior through Onacol
- [x] #2 All agent-facing commands have documented JSON schemas, stable IDs, bounded defaults, and consistent exit codes
- [x] #3 Errors are machine-readable in JSON mode and do not expose stack traces by default
- [x] #4 The CLI documents read-only PST guarantees, synchronization behavior, locking, and known libpff limitations
- [x] #5 Integration tests cover the documented command workflows and human-readable output remains usable
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Define complete agent-facing usage, schemas, safety, synchronization, limits, and exit-code contracts in Click help text.
2. Make JSON-mode success and failure output deterministic and machine-readable without default stack traces.
3. Create an OpenCode project skill that directs agents to command-level --help as the canonical documentation.
4. Add CLI contract and workflow tests, then run the project verification suite.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implementation: moved the agent-facing contract into root and command-level Click help, added stable JSON error envelopes with codes for JSON mode, added the project skill at .opencode/skills/pstq/SKILL.md, and corrected the README command table to include thread support.

Validation: uv run tox passed (Ruff, formatting, mypy, 104 tests, 100% coverage). Manually verified pstq --help, pstq search --help, pstq attachment --help, and JSON-mode invalid-input/configuration errors from the installed CLI.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @root
created: 2026-08-29 14:54
---
Agent: Implementation and verification are complete. All acceptance criteria are checked with lint: commands_pre[0]> uv sync --group dev
lint: commands[0]> uv run ruff check .
All checks passed!
lint: commands[1]> uv run ruff format --check .
10 files already formatted
lint: commands[2]> uv run mypy pstq
Success: no issues found in 6 source files
lint: OK ✔ in 0.58 seconds
py313: commands_pre[0]> uv sync --group dev
py313: commands[0]> uv run pytest --cov=pstq tests/
============================= test session starts ==============================
platform linux -- Python 3.13.15, pytest-9.1.1, pluggy-1.6.0
cachedir: .tox/py313/.pytest_cache
rootdir: /workspaces/pstq
configfile: pyproject.toml
plugins: cov-4.1.0
collected 104 items

tests/test_index.py ...............................................      [ 45%]
tests/test_metadata.py ...............                                   [ 59%]
tests/test_pst.py ....................                                   [ 78%]
tests/test_pstq.py ......................                                [100%]

---------- coverage: platform linux, python 3.13.15-final-0 ----------
Name               Stmts   Miss  Cover
--------------------------------------
pstq/__init__.py       3      0   100%
pstq/cli.py          231      0   100%
pstq/index.py        584      0   100%
pstq/metadata.py     157      0   100%
pstq/pst.py          297      0   100%
pstq/pstq.py           2      0   100%
--------------------------------------
TOTAL               1274      0   100%

Required test coverage of 100.0% reached. Total coverage: 100.00%

============================= 104 passed in 2.36s ==============================
  lint: OK (0.58=setup[0.08]+cmd[0.03,0.06,0.07,0.34] seconds)
  py313: OK (2.95=setup[0.01]+cmd[0.03,2.90] seconds)
  congratulations :) (3.56 seconds) and manual CLI help/error checks. This project has no review status, so the task remains In Progress for human review and acceptance.
---

author: @root
created: 2026-08-29 14:54
---
Agent correction: The immediately preceding status comment was malformed by shell command expansion. This comment and the replacement notes/final summary above are the accurate concise record: uv run tox passed with 104 tests and 100% coverage; the task remains In Progress for human review because no review status is configured.
---

author: Human
created: 2026-08-29 15:01
---
Human: Accepted the implementation and requested task closure.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added complete root and command-level --help contract documentation for configuration, JSON schemas, stable IDs, limits, exit codes, source/cache access, read-only PST safety, synchronization, locking assumptions, and libpff limitations. JSON-mode failures now use a stable stderr envelope with error code and message; text output remains usable. Added the project OpenCode pstq skill, which directs agents to command-level help as the canonical documentation, and corrected README command availability. Verified with uv run tox: 104 tests, lint, formatting, mypy, and 100% coverage. No ADRs or follow-up tasks created.
<!-- SECTION:FINAL_SUMMARY:END -->
