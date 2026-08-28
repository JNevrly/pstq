---
id: TASK-001.01
title: Prepare libpff reader integration
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-28 07:20'
updated_date: '2026-08-28 09:34'
labels: []
dependencies: []
references:
  - PST Search CLI — Implementation Brief.md
modified_files:
  - .devcontainer/Dockerfile
  - .devcontainer/devcontainer.json
  - pstq/pst.py
  - pstq/cli.py
  - tests/test_pst.py
  - tests/test_pstq.py
parent_task_id: TASK-001
priority: high
type: task
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Make the devcontainer reproducibly provide a pinned libpff/pypff build for Python 3.13. The native dependency must be fully available from the image without post-create installation or dependence on an editable workspace virtual environment. Maintain the narrow read-only PST adapter boundary and fake-based tests.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 The Dockerfile builds and imports libpff-python 20231205 from a SHA-256-verified source distribution with Python 3.13; postCreateCommand does not install pypff.
- [x] #2 The adapter opens PST files read-only and reports actionable errors for missing or unreadable files.
- [x] #3 The adapter retrieves and normalizes the message-store PidTagRecordKey as the store UID.
- [x] #4 The adapter exposes folder/message traversal, NIDs, modification times, and available mail properties needed by later tasks.
- [x] #5 Tests cover adapter behavior with fakes and do not require a real PST in CI.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Replace the current source checkout plus post-create wheel install with a Dockerfile-owned native dependency installation that remains visible to uv-managed virtual environments.
2. Use an immutable libpff source artifact and checksum so the build cannot drift with synclibs.sh dependency updates.
3. Reduce postCreateCommand to workspace initialization and uv dependency synchronization.
4. Build and import the resulting pypff wheel with Python 3.13, then run the project verification suite.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: the project has no PST adapter or pypff dependency yet. The devcontainer is Python 3.13 slim and can build libpff from source; current libpff HEAD resolved to e9b304c79a8dcdff7b11529022b2dfd8bf64a20f. The implementation will keep pypff optional at import time so fake-based tests run without a native build.

pypff API verification at libpff commit e9b304c79a8dcdff7b11529022b2dfd8bf64a20f: file.open(path, mode='r'), file.message_store, file.root_folder, folder get_sub_folder/get_sub_message, message identifier and modification_time, and record_set.get_entry_by_type(0x0FF9) are available. pypff recipient objects do not expose recipient-specific convenience getters; transport headers and raw message properties remain the available future boundary until a later binding extension.

Validation: built libpff commit e9b304c79a8dcdff7b11529022b2dfd8bf64a20f on Python 3.13 with PYTHON_VERSION=3.13 ./configure --enable-python, produced a cp313 wheel, installed it, and imported pypff successfully. The adapter opened temp/test.pst, normalized store UID edc4f1c4c743ad49a590c83842fd889f, and traversed 15 folders. pypff raises OSError for some absent optional properties in this sample; the adapter treats those fields as unavailable without aborting traversal. Final verification: uv run tox passed lint, format, mypy, 16 tests, and the configured 100% coverage gate. The project has no review status, so the task remains In Progress pending human review and acceptance.

Reopened after review: the prior post-create uv pip install was removed by a later uv sync because pypff is outside the project lock. The revised implementation must make pypff image-owned and available independently of the workspace virtual environment.

Revision implementation: Docker now builds libpff-python 20231205 from its PyPI source distribution, verified against SHA-256 06c218be51321b16dc3b835185ee1cd2fa5c2a1ca856e0390c1d6e4ddf329250, then installs the wheel in the image system Python. postCreate recreates the workspace environment with system site packages and only synchronizes project dependencies. Direct validation confirmed the release remains importable after uv sync and the adapter traverses temp/test.pst. The release lacks get_entry_by_type and conversation_index; the adapter now falls back to record-set entries and treats absent optional fields as None.

Final revision verification: built the SHA-256-verified libpff-python 20231205 source distribution into a CPython 3.13 wheel, installed it into system site packages, recreated .venv with --system-site-packages, and confirmed pypff 20231205 imports from /usr/local/lib/python3.13/site-packages after uv sync. The adapter opened temp/test.pst, returned store UID edc4f1c4c743ad49a590c83842fd889f, and traversed 15 folders. uv run tox passed ruff, formatting, mypy, 17 tests, and 100% coverage.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @human
created: 2026-08-28 08:30
---
Human: Reviewed TASK-001.01 and approved it for closure.
---

author: @human
created: 2026-08-28 09:17
---
Human: Requested that pypff installation move from postCreateCommand into the Dockerfile, with reproducible native source inputs.
---

author: @human
created: 2026-08-28 09:34
---
Human: Verified the rebuilt container and approved TASK-001.01 for closure.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Revised the devcontainer so Docker builds libpff-python 20231205 from a SHA-256-verified PyPI source distribution in a builder stage and installs the wheel into the final image. postCreateCommand now only recreates the project virtual environment with system site packages and synchronizes project dependencies; it never installs pypff. Added compatibility for the release binding's record-entry traversal and unavailable optional properties. Verified the image-style system installation survives uv sync, traverses temp/test.pst (15 folders), and passes uv run tox (17 tests, lint, formatting, mypy, 100% coverage). No ADRs or follow-up tasks. Pending human review and acceptance.
<!-- SECTION:FINAL_SUMMARY:END -->
