---
id: TASK-001.02
title: Benchmark PST metadata traversal and snapshots
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-28 07:21'
updated_date: '2026-08-29 05:15'
labels: []
dependencies:
  - TASK-001.01
references:
  - PST Search CLI — Implementation Brief.md
parent_task_id: TASK-001
priority: high
type: spike
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Validate the real PST and pypff assumptions before building the cache. Provide inspect output plus durable metadata snapshots that can be compared across an Outlook update cycle.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 pstq inspect PATH reports libpff version, PST size, store UID, folder count, message count, duration, throughput, scan errors, and bounded sample messages
- [x] #2 Inspect supports deterministic JSON output
- [x] #3 A snapshot stores folder path/NID and message NID/folder NID/modification time without reading bodies or attachments
- [x] #4 A comparison reports new, missing, modified, moved, unchanged, and suspicious identity cases
- [x] #5 A real mounted PST is benchmarked and findings are recorded in this task before it enters review
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add metadata-only traversal records and deterministic snapshot serialization without materializing message bodies or attachments.
2. Implement `pstq inspect`, `snapshot`, and `compare-snapshots` commands with JSON output and actionable errors.
3. Cover inspection, snapshot, and comparison behavior with fake-reader tests.
4. Run the commands against `temp/test.pst`, record traversal findings, and execute the full verification suite.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Confirmed sample archive for local Phase 1 validation: `temp/test.pst` (2,431,607,808 bytes at discovery). It is a local binary input, not a committed test fixture. Use it for `pstq inspect`, metadata snapshots, and before/after Outlook-update comparison; CI must continue to use fakes and must not require this file.

Initial investigation: TASK-001.01 provides PstReader.walk(include_bodies=False), normalized store UID, folder NIDs/paths, message NIDs, and modification times. The CLI is still the template stub, so this task will establish the command group and metadata snapshot format. The real local archive remains excluded from CI.

Implementation and local benchmark: added `pstq inspect PATH [--json]`, `pstq snapshot PATH OUTPUT`, and `pstq compare-snapshots BEFORE AFTER [--json]`. Snapshots contain only format version, store UID, folder NID/path, and message NID/folder NID/modification time. The comparison retains detailed new/missing/modified/moved records, reports an unchanged count, and flags store UID changes, duplicate NIDs, and messages referencing unknown folders.

Real validation on `temp/test.pst`: libpff/pypff 20231205, 2,431,607,808 bytes, store UID `edc4f1c4c743ad49a590c83842fd889f`, 15 folders, 2,458 messages, 4.495 seconds, 546.9 messages/second, and zero scan errors. `pstq snapshot temp/test.pst temp/test.snapshot.json` completed; comparing the snapshot with itself reported 0 new/missing/modified/moved, 2,458 unchanged, and no store UID change. `temp/test.snapshot.json` is local/ignored and was not committed.

Verification: `uv run tox` passed ruff lint and format checks, mypy, 39 tests, and the 100% coverage gate.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-08-28 08:05
---
A sample PST archive has been copied to `temp/test.pst` for local validation.
---

author: @opencode
created: 2026-08-28 09:45
---
Agent: Implementation and verification are complete. The configured Backlog states have no review state, so the task remains In Progress for human review and acceptance.
---

author: @human
created: 2026-08-29 05:15
---
Human: Reviewed the completed task and requested its closure.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented metadata-only PST diagnostics, durable JSON snapshots, and snapshot comparison with identity warnings. Verified against the real local PST (15 folders, 2,458 messages in 4.495 seconds, no scan errors), a self-comparison, and `uv run tox` (39 tests, lint, format, mypy, 100% coverage). No ADRs or follow-up tasks.
<!-- SECTION:FINAL_SUMMARY:END -->
