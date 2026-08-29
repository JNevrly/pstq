---
id: TASK-001.13
title: Recover owner messages from quoted history
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-29 16:09'
updated_date: '2026-08-29 16:28'
labels: []
dependencies: []
references:
  - docs/adr/0003-reconstruct-threads-from-indexed-relationship-metadata.md
documentation:
  - docs/adr/0004-model-quoted-history-as-derived-messages.md
modified_files:
  - pstq/body.py
  - pstq/index.py
  - pstq/cli.py
  - pstq/default_config.yaml
  - tests/test_body.py
  - tests/test_index.py
  - tests/test_pstq.py
  - README.md
  - docs/adr/0004-model-quoted-history-as-derived-messages.md
  - test_config.yaml
parent_task_id: TASK-001
priority: high
type: feature
ordinal: 14000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Recover high-confidence owner-authored messages from quoted Outlook reply and forwarded history so thread output includes curated archive-owner contributions that are absent from Sent Items. Preserve native PST records and raw bodies; derived records remain reproducible cache data.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 thread returns high-confidence recovered owner messages as provenance-marked derived records without changing search results
- [x] #2 The analyzer recognizes English, Czech, German, and Japanese Outlook quoted header blocks while preserving ambiguous content
- [x] #3 Recovered records are deterministically deduplicated across repeated quote occurrences and suppressed when they exactly match a native indexed message
- [x] #4 Owner matching uses configured aliases and timezone-aware ordering uses a configured IANA timezone
- [x] #5 Derived data updates atomically on full and incremental synchronization and parser changes trigger a full rebuild
- [x] #6 Tests cover parsing, false-positive protection, deduplication, ordering, configuration, and thread output
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add a versioned, conservative multilingual body analyzer that returns authored content and quoted occurrences without changing raw PST storage. 2. Persist owner-matched derived records and per-source occurrence provenance in the disposable SQLite cache, using exact canonical fingerprints for deduplication and native-message suppression. 3. Thread owner aliases and IANA timezone through synchronization and append derived records to their containing real-message components in deterministic chronological order. 4. Add configuration, ADR 0004, CLI/README contract updates, and focused parser/index/CLI tests. 5. Run targeted and full verification, then prepare the task for human review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: quoted history is preserved in message.body_raw but removed from body_clean before FTS and thread output. The agreed scope is thread-only, high-confidence owner-authored extraction for English/Czech/German/Japanese headers; forwarded blocks are included and labeled as context. The archive has substantial recoverable history but also repeated nested copies and timezone-free dates, requiring provenance, strict deduplication, and configured aliases/timezone.

Implemented the versioned analyzer, derived-message and occurrence tables, exact canonical native suppression, owner alias/timezone cache freshness, and mixed thread output. Derived state is rebuilt from persisted raw bodies inside the existing atomic full or incremental sync transaction, avoiding rereads of unchanged PST bodies.

Validation: uv run tox passed Ruff, formatting, mypy, 117 tests, and 100% coverage. Parser tests cover complete localized blocks, HTML-rendering gaps, false positives, byte bodies, unparseable dates, owner aliases, forwarding context, deduplication, native suppression, thread ordering, config propagation, and history-context full rebuilds.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @opencode
created: 2026-08-29 16:21
---
Agent: Implementation is ready for human review. The configured workflow has no review status, so the task remains In Progress pending human acceptance.
---

author: Human
created: 2026-08-29 16:23
---
Human: Configure the shared test archive with owner email jnevrly@alps.cz, owner name Josef Nevrly, and timezone Europe/Prague.
---

author: Human
created: 2026-08-29 16:28
---
Human: Confirmed the owner-history recovery works and requested task closure.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added a versioned multilingual quoted-history analyzer and a provenance-bearing derived-message cache. The thread command now includes high-confidence owner-authored recovered replies and forwards, deduplicated across quoted occurrences and suppressed when an exact native message exists; search remains native-message-only. Added owner alias/timezone configuration, cache-freshness invalidation, ADR 0004, and operator documentation. Verified with uv run tox: Ruff, formatting, mypy, 117 tests, and 100% coverage. Known limitation: RTF-only and incomplete or edited quote structures are intentionally omitted.
<!-- SECTION:FINAL_SUMMARY:END -->
