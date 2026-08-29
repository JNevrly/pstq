---
id: TASK-007
title: Harden json error detection and no-command UX
status: To Do
assignee: []
created_date: '2026-08-29 15:25'
labels:
  - code-review
  - polish
dependencies: []
references: []
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
- [ ] #1 JSON error envelopes are selected based on the parsed --json option, not a substring scan of raw argv
- [ ] #2 A query or argument value equal to "--json" no longer changes the error output format
- [ ] #3 Invoking pstq with no subcommand shows help or a clear error rather than exiting silently
- [ ] #4 Legitimate onacol CLI config overrides continue to work
- [ ] #5 Tests cover the "--json"-as-value case and the no-subcommand case
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Route the error-format decision through parsed context state instead of `"--json" in args`.
2. Emit help/usage (or an explicit error) when no subcommand is resolved, while preserving config-override forwarding.
3. Add tests for the "--json"-as-value and no-command paths.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
<!-- SECTION:NOTES:END -->
