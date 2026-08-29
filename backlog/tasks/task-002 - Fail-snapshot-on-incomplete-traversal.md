---
id: TASK-002
title: Fail snapshot on incomplete traversal
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-29 15:25'
updated_date: '2026-08-29 17:38'
labels:
  - code-review
  - bug
dependencies: []
references:
  - PST Search CLI — Implementation Brief.md
modified_files:
  - pstq/cli.py
  - tests/test_pstq.py
priority: high
type: bug
ordinal: 2000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
`inspect_pst` wraps the folder walk in a broad `try/except` that records any
failure in `scan_errors` and then continues, building a `MetadataSnapshot` from
whatever partial data was collected before the error. The `snapshot` command
(`pstq/cli.py`) calls `inspect_pst(path, sample_size=0)` and immediately writes
`report.snapshot` to disk without ever inspecting `report.scan_errors`. It then
reports success: `Wrote snapshot with N messages to OUTPUT`.

As a result, a traversal that fails part-way through a large or partially
corrupt PST produces a truncated snapshot that is written and reported as
though it were complete. Because snapshots feed `compare-snapshots`, a truncated
BEFORE or AFTER file silently mis-classifies large numbers of messages as
`missing` or `new`, corrupting the diagnostic diff the snapshot workflow exists
to provide.

The `inspect` command already prints scan errors, so this defect is specific to
the durable-artifact path (`snapshot`).
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 snapshot refuses to write (or exits non-zero) when the underlying traversal recorded any scan error
- [x] #2 The failure is reported through the standard CLI error contract, including a specific error code in --json mode
- [x] #3 A successful snapshot is written only when traversal completed without recorded errors
- [x] #4 Tests cover a traversal that fails part-way and assert no partial snapshot file is left behind
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Inspect the established CLI error contract and snapshot tests.
2. Make snapshot reject inspections with recorded scan errors before any file write.
3. Add a regression test for an interrupted traversal that proves no snapshot artifact remains.
4. Run focused and full test checks, then prepare the task for review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Investigation: inspect_pst intentionally retains traversal failures in Inspection.scan_errors; inspect displays them diagnostically. snapshot currently writes report.snapshot unconditionally. Expected CLI failures use CliContractError and CliContractGroup emits its code in JSON mode, so snapshot must reject scan errors before calling write_snapshot. The snapshot command also needs to accept --json for this runtime error to reach the JSON contract.

Validation: uv run pytest --cov=pstq tests/ passed (126 tests, 100% coverage); uv run ruff check . passed; uv run ruff format --check . passed; uv run mypy pstq passed. The regression test invokes snapshot after a report with a recorded mid-traversal OSError and verifies exit code 1, incomplete_traversal in JSON output, and that the requested snapshot file does not exist.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Snapshot now refuses inspections with recorded scan errors before writing. It reports incomplete traversal through the standard CLI error contract using the incomplete_traversal JSON code, while successful scans retain their existing write behavior. Verified by the full 126-test suite at 100% coverage plus Ruff format/lint and mypy. No follow-up tasks or ADRs.
<!-- SECTION:FINAL_SUMMARY:END -->

<!-- SECTION:NOTES:END -->
