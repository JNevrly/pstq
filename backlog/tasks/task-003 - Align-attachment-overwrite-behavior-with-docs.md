---
id: TASK-003
title: Align attachment overwrite behavior with docs
status: To Do
assignee: []
created_date: '2026-08-29 15:25'
labels:
  - code-review
  - bug
dependencies: []
references:
  - PST Search CLI — Implementation Brief.md
priority: medium
type: bug
ordinal: 3000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The documented behavior of `attachment --output` contradicts the implementation
in two ways.

1. Behavior vs. documentation. `PstReader.extract_attachment` opens the output
   with exclusive creation (`destination.open("xb")`) and re-raises
   `FileExistsError`, so an existing target is never replaced. The `attachment`
   command help states the opposite: "names a new output file; existing files
   may be replaced by the operating system." The README's Command Reference also
   describes extraction without noting that an existing path is rejected.

2. Error classification. `FileExistsError` is a subclass of `OSError`. The CLI
   catches `OSError` and routes it through `_command_error`, which maps every
   `OSError` to the `source_error` code. A pre-existing destination file is a
   caller/output problem, not a PST source problem, so both the code and the
   message ("... cannot be read" style) mislead an agent about the cause.

Decide the intended contract (reject existing files, or overwrite) and make the
code, command help, and README agree, then classify the error accordingly.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The attachment overwrite contract is defined once and documented identically in command help and README
- [ ] #2 The implementation matches the documented contract
- [ ] #3 When the output path already exists (if rejection is chosen), the failure returns a distinct, accurate error code rather than source_error
- [ ] #4 Tests cover the existing-output-path case and assert the chosen behavior and error envelope
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Confirm the intended behavior for an existing output path (reject is the current safe default).
2. Add a dedicated exception/error code for output-path conflicts and stop mapping it to source_error.
3. Correct the `attachment` command help and the README Command Reference.
4. Add tests for both the fresh-write and existing-path cases, including the JSON error envelope.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
<!-- SECTION:NOTES:END -->
