---
id: TASK-001.07
title: Add thread reconstruction command
status: Done
assignee:
  - '@root'
created_date: '2026-08-28 07:21'
updated_date: '2026-08-29 14:43'
labels: []
dependencies:
  - TASK-001.05
references:
  - PST Search CLI — Implementation Brief.md
  - docs/adr/0003-reconstruct-threads-from-indexed-relationship-metadata.md
modified_files:
  - pstq/cli.py
  - pstq/index.py
  - pstq/pst.py
  - tests/test_index.py
  - tests/test_pst.py
  - tests/test_pstq.py
  - docs/adr/0003-reconstruct-threads-from-indexed-relationship-metadata.md
parent_task_id: TASK-001
priority: medium
type: task
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Store usable message relationship metadata and provide chronological per-message thread retrieval independent of quote stripping.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Importer persists available Internet Message-ID, In-Reply-To, References, conversation topic, and conversation index values
- [x] #2 thread accepts a stable message ID and returns related indexed messages in deterministic chronological order
- [x] #3 Thread retrieval displays individual message contributions and does not concatenate repeated quoted bodies
- [x] #4 Missing or malformed relationship metadata produces a useful partial thread rather than failing the command
- [x] #5 Tests cover header-based relations, conversation fallback, ordering, and missing data
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Extract relationship properties from PST MAPI record sets, falling back to transport headers when necessary, and bump the disposable cache schema version.
2. Add SQLite-only thread reconstruction from header relations, then conversation-index root, then conservative exact conversation-topic fallback; document the strategy in an ADR.
3. Add the thread CLI with deterministic JSON envelope and separate cleaned message contributions.
4. Add metadata, reconstruction, ordering, partial-data, and CLI tests.
5. Run targeted and full checks, then prepare the task for human review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Investigation confirmed that pypff 20231205 does not expose message.conversation_index directly, although MAPI PidTagConversationIndex (0x0071) is present in record sets. Existing relationship columns remain usable, but cache version must change to repopulate conversation-index data.

Implementation: added MAPI record-set extraction for the five relationship properties, with transport-header fallback for Thread-Topic and valid Thread-Index. Schema version 6 atomically rebuilds caches with this corrected metadata. get_thread() builds an in-memory indexed Message-ID component, falling back only to matching conversation-index roots and then exact case-folded topic; it returns individually cleaned records sorted by normalized effective date and NID. The CLI reads SQLite only and returns an id/messages JSON envelope. ADR 0003 records this strategy and the later normalized-relation-table option.

Validation: `uv run tox` passed Ruff, mypy, and 103 tests at 100% coverage. A configured real-PST sync then `thread edc4f1c4c743ad49a590c83842fd889f:2173156 --json` returned the chronological thread. The rebuilt cache has 2,458 messages and 2,458 non-null conversation indexes; `PRAGMA integrity_check` returned ok and `foreign_key_check` returned no violations.

Documentation: TASK-001.09 remains responsible for final command-contract and operator documentation; README previously marked thread unavailable and should be updated there.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @root
created: 2026-08-29 13:55
---
Human: Approved implementation and requested an ADR for the thread-tracking strategy so later development phases can revisit it.

Agent: Agreed contract: SQLite-only thread reads; JSON envelope containing ordered full cleaned message records; explicit Message-ID graph first, conversation-index root only when that yields no indexed relatives, then exact case-insensitive topic only when neither stronger source yields relatives.
---

author: @root
created: 2026-08-29 14:03
---
Agent: Implementation is ready for human review. All acceptance criteria are verified; this Backlog configuration has no review state, so TASK-001.07 remains In Progress pending human acceptance.
---

author: Human
created: 2026-08-29 14:43
---
Human: Reviewed the implementation, confirmed it works, and approved closure.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented SQLite-only thread reconstruction and `pstq thread MESSAGE_ID [--json]`. The importer now reads relationship metadata from PST MAPI record sets with transport-header fallback, and schema version 6 rebuilds stale caches. Threading uses header graph relations first, then conservative conversation-index and exact-topic fallbacks; output returns individual cleaned contributions in deterministic chronological order. ADR 0003 documents the strategy and future normalized-relation-table option. Verified with `uv run tox` (103 tests, 100% coverage) and a real PST rebuild/thread query; no known limitations beyond the documented full-store metadata scan per thread query. TASK-001.09 owns final CLI/README documentation updates.
<!-- SECTION:FINAL_SUMMARY:END -->
