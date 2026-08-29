---
id: TASK-001.14
title: Search recovered owner responses
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-29 16:28'
updated_date: '2026-08-29 17:17'
labels: []
dependencies:
  - TASK-001.13
references:
  - docs/adr/0004-model-quoted-history-as-derived-messages.md
  - docs/adr/0005-unify-native-and-recovered-message-search.md
modified_files:
  - README.md
  - pstq/cli.py
  - pstq/index.py
  - tests/test_index.py
  - tests/test_pstq.py
  - docs/adr/0005-unify-native-and-recovered-message-search.md
parent_task_id: TASK-001
priority: high
type: feature
ordinal: 15000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Make recovered owner-authored messages indistinguishable from native messages at the CLI/UI layer. The existing search command must search one combined native-and-recovered corpus using its normal FTS5 syntax and result contract. Recovery provenance remains internal cache data only.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 search QUERY searches native and enabled recovered messages together with one bounded deterministic ranking and unchanged FTS5 syntax
- [x] #2 Unified results, show, and thread expose only ordinary message fields; they do not expose record_type, relation, or recovery provenance
- [x] #3 Recovered messages retain stable existing selectors, work with show and thread, and use their deterministic canonical source folder
- [x] #4 Existing filters apply consistently: recovered messages match their canonical source folder and never satisfy has-attachment
- [x] #5 --from-owner OR-matches all configured owner email and name aliases, is mutually exclusive with --from, and errors when no aliases are configured
- [x] #6 Recovery-disabled caches return native results only, and all derived search data is atomically rebuilt and removed on full and incremental synchronization
- [x] #7 search-recovered and all recovery-specific user-facing output and documentation are removed
- [x] #8 Tests cover mixed FTS matching/ranking/bounds, filters, owner aliases, canonical folders, hidden recovery metadata, retrieval, disabled recovery, deduplication, and synchronization cleanup
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Replace separate native/recovered FTS indexes with a unified search-document projection that stores result-contract metadata and a single FTS5 corpus. 2. Rebuild recovered documents atomically with derived messages and occurrences, selecting the lowest source message ID and quote position as each recovered record's canonical source. 3. Extend the normal search API and CLI to query the combined corpus and add --from-owner alias expansion while removing search-recovered. 4. Make show and thread resolve recovered selectors but render the normal message schema, and keep attachment output empty for recovered selectors. 5. Document the unified contract, add ADR 0005, revise focused tests, run full verification, and prepare for review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Review change: recovery is an internal indexing detail. Human confirmed that search, show, and thread must hide recovery metadata; recovered messages use their existing stable selectors and a deterministic canonical source folder. --from-owner matches all configured owner name and email aliases. Recovered messages never satisfy --has-attachment.

Created ADR 0005 to record the unified native/recovered search projection and hidden recovery UI boundary.

Implemented schema version 9 with a unified search_document projection and search_fts corpus. Native documents update incrementally; derived documents are deleted and rebuilt inside the existing atomic synchronization transaction. Recovered selectors resolve to ordinary show/thread records using the lowest source NID and quote position as canonical source. Removed search-recovered, added --from-owner, updated README and ADR 0005. Final validation: uv run tox passed Ruff, formatting, mypy, 120 tests, and 100% coverage.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @opencode
created: 2026-08-29 16:39
---
Agent: Implementation is ready for human review. This workflow has no review status, so the task remains In Progress pending human acceptance.
---

author: Human
created: 2026-08-29 16:49
---
Human: Recovery must not be propagated to the CLI/UI. Search should query native and recovered messages together using the existing syntax. --from-owner should match all configured owner aliases; recovered messages use a canonical source folder, retain existing selectors, and recovery-specific fields are hidden everywhere.
---

author: @opencode
created: 2026-08-29 17:01
---
Agent: Revised implementation is ready for human review. The workflow has no review status, so the task remains In Progress pending human acceptance.
---

author: Human
created: 2026-08-29 17:17
---
Human: Accepted the revised unified-search implementation and requested task closure.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Replaced the separate recovered-search UI with one schema-9 FTS projection for native and owner-history messages. The normal search command now applies global FTS ranking and existing filters to both kinds, with deterministic canonical source folders and no recovery-specific result fields. Recovered selectors work with show and thread as ordinary messages; attachments are empty. Added --from-owner for all configured aliases, removed search-recovered, and documented ADR 0005. Verified with uv run tox: Ruff, formatting, mypy, 120 tests, and 100% coverage. No known limitations or follow-up tasks beyond the existing deliberate conservative quote parsing.
<!-- SECTION:FINAL_SUMMARY:END -->
