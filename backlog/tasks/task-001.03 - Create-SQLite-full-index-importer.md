---
id: TASK-001.03
title: Create SQLite full-index importer
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-28 07:21'
updated_date: '2026-08-29 05:20'
labels: []
dependencies:
  - TASK-001.02
references:
  - PST Search CLI — Implementation Brief.md
modified_files:
  - pstq/index.py
  - tests/test_index.py
parent_task_id: TASK-001
priority: high
type: task
ordinal: 4000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Create the disposable SQLite cache and its first full importer from the normalized PST reader. Persist enough normalized mail data for later retrieval without reopening the PST.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Schema stores one PST store, folders, messages, recipients, and attachment metadata using store UID plus NID uniqueness
- [x] #2 Messages preserve a selected raw body plus its source format and parsed relationship metadata where available
- [x] #3 A full import is transactional and leaves the prior usable index intact on failure
- [x] #4 Deleting the SQLite database followed by a full import recreates equivalent indexed records from the PST
- [x] #5 Schema and importer tests cover representative normalized records without requiring a real PST
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Define a SQLite schema for a single PST cache with composite store UID/NID identities and normalized folders, messages, recipients, and attachment metadata.
2. Import the full normalized reader traversal into a sibling temporary SQLite database, choose one raw body with its format, parse available mail relationship headers, then atomically replace the cache only on success.
3. Add fake-reader schema and import tests covering persisted records, body selection/relationship parsing, failed-import preservation, and rebuild equivalence.
4. Run the focused and full test suites, record verified results, and prepare the task for human review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: PstReader.walk(include_bodies=True) yields PstFolder and PstMessage records with all fields required by this task. The current reader does not yet expose recipient or per-attachment metadata; the schema will provide their normalized tables now, while populated fields remain limited to the current normalized records. Task 001.08 will extend reader/import population for attachment details.

Implementation: added pstq.index.import_pst. It creates store, folder, message, recipient, and attachment tables using composite store UID/NID relationship keys; the reader currently has no recipient or per-attachment metadata, so those tables are intentionally empty until TASK-001.08 extends the normalized reader. Messages select plain text, then HTML, then RTF as body_raw and record body_format. HeaderParser persists Message-ID, In-Reply-To, and References when transport headers are available.

Safety: each import writes to a temporary database beside the target, commits it, and uses os.replace only after successful traversal, preserving an existing cache on traversal or replacement failure.

Validation: tests/test_index.py uses a fake reader and verifies schema records, body fallback, relationships, failure preservation, and deletion/rebuild equivalence. uv run tox passed: Ruff lint/format, mypy, and 47 tests at 100% coverage. Local ignored real-PST validation via import_pst(temp/test.pst, temp/test.index.sqlite) succeeded with store UID edc4f1c4c743ad49a590c83842fd889f, 15 folders, and 2,458 messages.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @opencode
created: 2026-08-29 05:19
---
Agent: Implementation and verification are complete. The configured Backlog states have no review state, so this task remains In Progress for human review and acceptance.
---

author: @human
created: 2026-08-29 05:20
---
Human: End-to-end testing is difficult at this stage; close the task based on the completed automated and local-import verification.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented a disposable SQLite full importer in pstq.index with normalized store, folder, message, recipient, and attachment schema. Imports build a sibling temporary database and atomically replace the active cache only after a successful traversal; raw body format and available reply/thread headers are retained. Verified with fake-reader schema/import tests, a deleted-cache rebuild test, failure-preservation tests, real local PST import (15 folders, 2,458 messages), and uv run tox (Ruff, mypy, 47 tests, 100% coverage). Recipient and detailed attachment rows await normalized reader support in TASK-001.08; no ADRs created.
<!-- SECTION:FINAL_SUMMARY:END -->
