---
id: TASK-008
title: Incrementally rebuild recovered messages
status: Done
assignee:
  - '@Josef'
created_date: '2026-08-30 08:30'
updated_date: '2026-08-30 16:14'
labels:
  - code-review
  - performance
dependencies:
  - TASK-001.13
  - TASK-005
references:
  - docs/adr/0004-model-quoted-history-as-derived-messages.md
priority: medium
type: enhancement
ordinal: 8000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
When quoted-history recovery is enabled (`history.owner_emails` or
`history.owner_names` configured), `_rebuild_recovered_messages` reprocesses the
entire store on every synchronization:

```sql
SELECT nid, sender_name, subject, client_submit_time, delivery_time,
       transport_headers, body_raw, body_clean, body_format
FROM message WHERE store_uid = ?
```

For each returned row it re-renders the raw body (`_render_body`) and re-runs
`analyze_body`, then rebuilds all derived tables. This has two costs:

1. It defeats the incremental-sync optimization. `_incremental_sync` deliberately
   reads bodies only for new or modified messages, but then calls
   `_rebuild_recovered_messages`, which re-renders and re-analyzes *every* message
   body in the store even when a single message changed. On a large archive an
   otherwise cheap incremental sync becomes O(all messages) in body work.
2. It duplicates work already performed during `_upsert_message`, where
   `clean_body(_render_body(...))` already renders and analyzes each changed
   body. Each changed body is therefore rendered and analyzed at least twice per
   sync.

The full-store pass exists because deduplication and the exact-native-duplicate
suppression are defined across the whole store. The goal is to keep that global
correctness while making the steady-state cost scale with the number of changed
messages, e.g. by persisting per-message extracted quotes keyed by
`nid` + `modification_time` (or generation) and re-deriving only the aggregate
recovered/occurrence/search rows from that cache. Behavior must remain identical;
this is purely a performance change.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 An incremental sync that changes a small number of messages does not re-render or re-analyze every message body in the store
- [x] #2 A changed message body is not rendered and analyzed more than once per synchronization
- [x] #3 Recovered-message, quote-occurrence, dedup, and search results are unchanged for existing fixtures
- [x] #4 Global deduplication and exact-native-duplicate suppression remain correct after partial updates
- [x] #5 A regression test demonstrates that a single-message incremental sync performs bounded body analysis
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a schema-versioned per-native-message quote cache.
2. Populate or replace cache rows while a new or modified message body is already rendered and analyzed during full or incremental sync.
3. Rebuild recovered messages, occurrences, and recovered search rows globally from cached quotes plus current native fingerprints.
4. Add regression coverage for one-message incremental work and output preservation, then run focused and full tests.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Investigation confirmed _rebuild_recovered_messages was the only full-store body render/analyze pass. Implemented schema version 11 with quote_cache, populated during _upsert_message; rederivation now reads cached owner quotes and current native fingerprints. Cached quote bodies preserve unresolved CIDs so attachment changes do not alter quote identity.

Validation passed: uv run tox (ruff lint and format checks, mypy, 132 tests, 100% coverage). The incremental regression instruments rendering and analysis, verifies exactly one call for one modified message, and verifies global exact-native suppression plus recovered search and occurrences.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Implemented schema version 11 quote caching per source message. Changed-body upserts render and analyze once, cache owner quotes, and recovery rederives global recovered rows from that cache while retaining current native duplicate suppression. Verified with uv run tox: lint, formatting, mypy, 132 tests, and 100% coverage. No ADRs or follow-up tasks.
<!-- SECTION:FINAL_SUMMARY:END -->

<!-- SECTION:NOTES:END -->
