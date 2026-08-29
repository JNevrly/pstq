---
id: TASK-003
title: Align attachment overwrite behavior with docs
status: Done
assignee: []
created_date: '2026-08-29 15:25'
updated_date: '2026-08-29 17:44'
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
- [x] #1 The attachment overwrite contract is defined once and documented identically in command help and README
- [x] #2 The implementation matches the documented contract
- [x] #3 When the output path already exists (if rejection is chosen), the failure returns a distinct, accurate error code rather than source_error
- [x] #4 Tests cover the existing-output-path case and assert the chosen behavior and error envelope
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Retain exclusive output creation so attachment extraction never overwrites an existing file.
2. Map FileExistsError before the general OSError classification to the dedicated output_exists CLI error, with an output-specific message.
3. State the no-overwrite contract identically in attachment help and the README command reference.
4. Add regression coverage for the retained reader behavior and the CLI human and JSON error envelopes, then run targeted and full checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
<!-- SECTION:NOTES:BEGIN -->

Validated the attachment help text directly with `uv run pstq attachment --help`; it states the same no-overwrite contract as README.md. `tests/test_pst.py::test_attachment_metadata_and_locator_extraction_use_anonymous_fixture` verifies exclusive creation preserves the original output. `tests/test_pstq.py::test_attachment_command_rejects_existing_output_path` verifies text and JSON failures use output_exists. Full validation: `uv run tox` passed lint, formatting, mypy, 127 tests, and 100% coverage.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Retained safe exclusive attachment output creation and documented that existing output paths are never overwritten. Added attachment --json error support and mapped output conflicts to the output_exists error envelope.

Verification: `uv run tox` passed lint, formatting, mypy, 127 tests, and 100% coverage. No ADRs or follow-up tasks were needed.
<!-- SECTION:FINAL_SUMMARY:END -->

Investigation confirmed PstReader.extract_attachment uses exclusive "xb" creation and cleans only files it created after a failed write. The CLI currently classifies FileExistsError as source_error because it checks OSError broadly. The attachment command does not advertise --json, but its group-level failure renderer emits JSON when --json is present; task-007 separately covers broader no-command/JSON UX.
<!-- SECTION:NOTES:END -->

<!-- SECTION:NOTES:END -->
