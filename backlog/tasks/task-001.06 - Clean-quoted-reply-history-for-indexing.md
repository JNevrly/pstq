---
id: TASK-001.06
title: Clean quoted reply history for indexing
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-28 07:21'
updated_date: '2026-08-29 08:55'
labels: []
dependencies:
  - TASK-001.05
references:
  - PST Search CLI — Implementation Brief.md
modified_files:
  - pstq/index.py
  - pstq/pst.py
  - tests/test_index.py
parent_task_id: TASK-001
priority: medium
type: task
ordinal: 7000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Create a replaceable body-cleaning stage that conservatively removes clearly quoted Outlook reply history. Preserve unmodified raw text and reindex cleaned content.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Raw message body and its source format remain unchanged in SQLite
- [x] #2 Cleaning removes only recognized original-message separators and high-confidence Outlook header blocks
- [x] #3 Ambiguous content remains searchable
- [x] #4 Normal FTS indexes cleaned body content instead of raw body content
- [x] #5 Changing the cleaner version requires and performs a full reindex
- [x] #6 Tests cover plain-text quoted replies, false-positive protection, and reindexing
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a versioned, conservative cleaner that truncates only recognized Outlook quoted-history markers.
2. Persist raw and cleaned bodies separately; populate FTS from the cleaned representation.
3. Record cleaner version in index state so a version change triggers atomic full reindexing.
4. Add focused tests for cleaning, false-positive preservation, FTS behavior, and reindexing.

5. Preserve byte-valued bodies in raw storage while decoding only the cleaned FTS representation, then cover the production reader behavior with an end-to-end regression test.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: `pstq/index.py` stores `message.body_raw` and `body_format`, and FTS previously indexed raw text. `sync_pst()` already performs an atomic full rebuild when stored schema version mismatches `SCHEMA_VERSION`; cleaner-version invalidation uses the same path while retaining an explicit cleaner version in index state. `get_message()` returns the raw body, so retrieval behavior remains unchanged.

Implemented schema version 3 with `message.body_clean` and persisted `index_state.cleaner_version`. `clean_body()` only truncates at an exact `-----Original Message-----` separator or a populated, ordered English Outlook `From`/`Sent`/`To`/optional `Cc`/`Subject` block. FTS reads `body_clean`; message retrieval continues to return `body_raw`.

Validation passed: `uv run tox` completed lint, formatting, mypy, 79 tests, and 100% coverage.

Regression reported after first real indexing attempt: pypff returned a byte-valued body and `clean_body()` passed it to a string regex. The original fake-reader tests supplied only strings. The fix will retain the raw bytes in SQLite and decode only the clean FTS value.

Fixed byte-valued PST bodies: PstMessage body fields now model strings or bytes; raw bytes remain persisted unchanged, while clean_body decodes bytes with replacement only for FTS cleaning. Added a full-import regression test using a byte body and quote separator. Verified `uv run tox` (80 tests, 100% coverage) and `.venv/bin/pstq --config test_config.yaml search chocolate`, which completed indexing and returned results.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @opencode
created: 2026-08-29 08:55
---
Human: The first real search-triggered indexing run failed because a byte-valued PST body reached the string quote-cleaner regex.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added versioned conservative Outlook quote cleaning with separate raw and cleaned SQLite body fields. FTS indexes cleaned text while retrieval preserves the raw body and format. Byte-valued pypff bodies now remain raw bytes in SQLite and are decoded only for cleaned FTS text, preventing the real indexing crash. Cleaner-version mismatch triggers an atomic full rebuild. Verified with `uv run tox` (ruff, formatting, mypy, 80 tests, 100% coverage) and `.venv/bin/pstq --config test_config.yaml search chocolate` against the configured PST.
<!-- SECTION:FINAL_SUMMARY:END -->
