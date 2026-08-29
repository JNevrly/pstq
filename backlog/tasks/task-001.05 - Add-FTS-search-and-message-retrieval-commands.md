---
id: TASK-001.05
title: Add FTS search and message retrieval commands
status: Done
assignee:
  - '@root'
created_date: '2026-08-28 07:21'
updated_date: '2026-08-29 08:39'
labels: []
dependencies:
  - TASK-001.04
references:
  - PST Search CLI — Implementation Brief.md
modified_files:
  - pstq/cli.py
  - pstq/default_config.yaml
  - pstq/index.py
  - tests/test_index.py
  - tests/test_pstq.py
parent_task_id: TASK-001
priority: high
type: task
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add the primary agent workflow: status, folders, lexical search, and message display from SQLite. Search must synchronize first when the configured PST changed.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 status reports index freshness and source/index metadata
- [x] #2 folders returns stable folder paths and identifiers
- [x] #3 search blocks for synchronization when required and searches FTS5 with bounded results
- [x] #4 Search supports query, sender, recipient, date range, folder, attachment, limit, and JSON options
- [x] #5 Search results omit full bodies and include stable ID, date, participants, subject, folder, snippet, and score
- [x] #6 show retrieves the complete persisted message from SQLite without opening an unchanged PST
- [x] #7 Tests cover SQL filtering, FTS query handling, JSON output, and automatic freshness behavior
- [x] #8 Search handles malformed text in indexed PST content without raising a UTF-8 decoding error
- [x] #9 show JSON safely serializes byte-valued PST fields using replacement decoding
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Extend the disposable SQLite schema with an FTS5 message index and persisted header-derived recipients, rebuilding stale schema versions through the existing synchronization path.
2. Add read-only index APIs for cache status, stable folder listing, bounded FTS search with SQL filters, and full persisted-message retrieval.
3. Add configured CLI commands for status, folders, search, and show; search synchronizes the configured PST before querying while show reads SQLite only.
4. Cover FTS/query-filter behavior, JSON output, and automatic freshness synchronization, then run the full project checks.

5. Decode SQLite text results with replacement for malformed UTF-8 and add a regression test using an invalid FTS snippet.

6. Normalize byte-valued SQLite message and recipient fields to replacement-decoded text before show constructs JSON.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: index.py has atomic synchronization and normalized cache tables but no FTS/query API. PstMessage does not yet expose recipients; transport headers can supply persisted To/Cc/Bcc values without expanding PST-reader scope. The existing configuration contains only logging, so these commands need explicit configured PST and index paths through the established Onacol manager. TASK-001.06 will later change FTS body input from body_raw to body_clean; TASK-001.08 owns detailed attachment metadata.

Implementation: schema version 2 adds an FTS5 index populated from subject, sender, header-derived recipients, and the currently persisted raw body. Normalized To/Cc/Bcc rows support recipient filtering. Added read-only status, folder, FTS search, and full-message retrieval APIs; message and folder IDs are store UID plus NID. The CLI accepts archive.pst_path and archive.index_path through Onacol; search synchronizes before querying, while show reads SQLite only.

UTF-8 regression: FTS5 snippets can preserve malformed byte sequences from PST HTML. The search connection now uses a SQLite text factory that decodes all result text as UTF-8 with replacement characters, keeping valid search hits usable rather than failing during Python result decoding.

Validation: uv run tox passed Ruff lint/format, mypy, and 73 tests at 100% coverage. The regression test injects invalid UTF-8 into an FTS snippet and asserts a replacement character is returned. Local search against temp/test.pst for chocolate completed in both text and JSON modes, including the previously failing D�sseldorf snippet.

Show regression investigation: message 2173156 stores at least one persisted field as a SQLite BLOB. get_message returns bytes unchanged, causing json.dumps in show --json to raise TypeError.

Show fix: get_message now applies replacement decoding to SQLite TEXT and BLOB-backed message and recipient fields before returning its JSON-ready dictionary. This preserves the persisted content while ensuring no bytes reach json.dumps.

Validation update: uv run tox passed Ruff lint/format, mypy, and 74 tests at 100% coverage. The byte-field regression test updates the cached body and recipient email to invalid UTF-8 bytes, verifies replacement-decoded output, and serializes the complete message. The reported show --json command for message 2173156 completed successfully against temp/test.pst.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @root
created: 2026-08-29 06:14
---
Agent: Implementation is ready for human review. The configured Backlog states have no review state, so the task remains In Progress pending acceptance.
---

author: @root
created: 2026-08-29 07:40
---
Human: Reported that search chocolate crashed while SQLite decoded a malformed UTF-8 FTS snippet from the test PST.
---

author: @root
created: 2026-08-29 07:40
---
Agent: Reproduced the failure, added replacement decoding and a regression test, then verified text and JSON chocolate searches against the test PST.
---

author: Human
created: 2026-08-29 08:12
---
Human: Reported that show --json for message 2173156 raised TypeError because the returned record contained bytes.
---

author: @root
created: 2026-08-29 08:12
---
Agent: Reproduced the BLOB serialization failure, normalized persisted text and byte values with replacement decoding, and verified the exact show command plus the full test suite.
---

author: Human
created: 2026-08-29 08:39
---
Human: Accepted the implementation and requested closure of TASK-001.05.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented configured status, folders, search, and show commands backed by a versioned SQLite FTS5 cache. Search synchronizes the PST before bounded lexical queries with structured filters; show uses only the persisted cache. SQLite TEXT and BLOB values from malformed PST content are decoded with replacement before search/show output, so snippets and complete-message JSON remain usable. Verified by uv run tox (74 tests, 100% coverage), local chocolate search, and the reported show --json retrieval from temp/test.pst. TASK-001.06 will switch FTS body input from raw to cleaned text; TASK-001.08 will add detailed attachment metadata. No ADRs created.
<!-- SECTION:FINAL_SUMMARY:END -->
