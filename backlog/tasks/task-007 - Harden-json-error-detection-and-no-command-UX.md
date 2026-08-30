---
id: TASK-007
title: Harden json error detection and no-command UX
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-29 15:25'
updated_date: '2026-08-30 06:12'
labels:
  - code-review
  - polish
dependencies: []
modified_files:
  - pstq/cli.py
  - tests/test_pstq.py
priority: low
type: enhancement
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Two smaller robustness/UX issues in the CLI entry group:

1. Error-envelope format detection is a raw membership test. `CliContractGroup`
   decides whether to emit a JSON error envelope with `"--json" in args` over the
   unparsed argument list (`_json_requested`). This is decoupled from Click's own
   parsing, so a positional value that happens to equal `--json` (for example a
   search QUERY of `--json`) would flip an otherwise text-mode command into JSON
   error output, and any future short alias would be missed. Detection should be
   tied to the actually-parsed option rather than a substring scan of argv.

2. No-subcommand invocation is silent. The group is declared with
   `invoke_without_command=True` plus `allow_extra_args`/`ignore_unknown_options`
   so unknown top-level tokens are forwarded to onacol as config overrides.
   Running `pstq --config pstq.yaml` with no command validates config and exits 0
   with no output, and a mistyped command name is swallowed as a config token
   instead of producing an "unknown command" error. Show help (or a clear error)
   when no valid subcommand is given, without breaking legitimate onacol
   overrides.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 JSON error envelopes are selected based on the parsed --json option, not a substring scan of raw argv
- [x] #2 A query or argument value equal to "--json" no longer changes the error output format
- [x] #3 Invoking pstq with no subcommand shows help or a clear error rather than exiting silently
- [x] #4 Legitimate onacol CLI config overrides continue to work
- [x] #5 Tests cover the "--json"-as-value case and the no-subcommand case
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Use the active Click context’s parsed `json_output` parameter when rendering handled errors.
2. Render group help after configuration setup when no subcommand was resolved, leaving `ctx.args` available to onacol for configuration overrides.
3. Add regression tests for `--json` as a positional query and no-subcommand help, then run the focused suite and static checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
<!-- SECTION:NOTES:BEGIN -->

Implementation: contract errors retain their active Click context; error rendering walks parsed context parameters for `json_output`. JSON flags are eager so Click records the selected mode before another option can fail parsing. Unknown top-level tokens are retained as Onacol arguments when no command resolves, then the group callback renders help after config validation.

Verification: `.venv/bin/pytest` (131 passed); `.venv/bin/ruff check .` (passed); `.venv/bin/mypy pstq` (passed); `git diff --check` (passed, with only Git CRLF normalization warning for the pre-existing test file line ending).
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Replaced raw argv JSON detection with parsed Click context state, retained Onacol config overrides when no command resolves, and render help instead of silently succeeding. Added regressions for a literal `--json` query, bare no-command invocation, and no-command overrides. Verified with 131 passing tests, Ruff, MyPy, and diff checks. No ADRs or follow-up tasks.
<!-- SECTION:FINAL_SUMMARY:END -->

Initial investigation: `CliContractGroup.main()` chooses JSON formatting with a raw `"--json" in args` check. The group callback validates config and returns without output if no subcommand resolves; `ctx.args` carries Onacol overrides. Relevant coverage is in `tests/test_pstq.py`.
<!-- SECTION:NOTES:END -->

<!-- SECTION:NOTES:END -->
