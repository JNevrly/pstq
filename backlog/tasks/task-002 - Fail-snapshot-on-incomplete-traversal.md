---
id: TASK-002
title: Fail snapshot on incomplete traversal
status: To Do
assignee: []
created_date: '2026-08-29 15:25'
labels:
  - code-review
  - bug
dependencies: []
references:
  - PST Search CLI — Implementation Brief.md
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
- [ ] #1 snapshot refuses to write (or exits non-zero) when the underlying traversal recorded any scan error
- [ ] #2 The failure is reported through the standard CLI error contract, including a specific error code in --json mode
- [ ] #3 A successful snapshot is written only when traversal completed without recorded errors
- [ ] #4 Tests cover a traversal that fails part-way and assert no partial snapshot file is left behind
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Surface `scan_errors` from `inspect_pst` to the `snapshot` command.
2. Raise a CLI contract error before writing when `scan_errors` is non-empty, and avoid leaving a partial output file.
3. Decide whether `inspect` should keep tolerating scan errors (diagnostic) while `snapshot` treats them as fatal.
4. Add regression tests using a fake reader that raises mid-walk.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
<!-- SECTION:NOTES:END -->
