---
id: TASK-001.15
title: Resolve quoted CID images through source attachments
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-29 17:16'
updated_date: '2026-08-29 17:28'
labels: []
dependencies:
  - TASK-001.14
references:
  - docs/adr/0004-model-quoted-history-as-derived-messages.md
  - docs/adr/0005-unify-native-and-recovered-message-search.md
modified_files:
  - pstq/index.py
  - tests/test_index.py
parent_task_id: TASK-001
priority: medium
type: enhancement
ordinal: 16000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Resolve exact embedded cid: image references in quoted owner-history message bodies against attachment metadata on the recovered message's canonical source. Render an existing extractable attachment marker when the reference is unambiguous, without exposing recovery provenance or attributing source attachments generally.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 An exact normalized match between a quoted cid: image reference and the canonical source message attachment content_id renders as [attachment: ATTACHMENT_ID].
- [x] #2 The emitted attachment ID works with the existing attachment ATTACHMENT_ID --output FILE command.
- [x] #3 CID matching ignores case and surrounding angle brackets.
- [x] #4 Missing or ambiguous CID matches remain [image: unresolved cid:...].
- [x] #5 Matching is limited to the canonical source message and does not infer links from filename, content location, or unrelated attachments.
- [x] #6 Ordinary native-message image rendering remains unchanged and recovery provenance remains absent from CLI output.
- [x] #7 Full and incremental synchronization rebuild resolved markers atomically when source messages or attachments change.
- [x] #8 Tests cover successful resolution, extraction ID validity, absent metadata, duplicate CID ambiguity, canonical-source selection, and synchronization cleanup.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Trace derived-message rebuilding and canonical-source selection to identify the narrow rendering hook. 2. Build an unambiguous normalized content-ID map from only the canonical source attachment rows and render quoted HTML CID images through the existing safe marker behavior. 3. Bump the disposable cache render version and add focused tests for resolution, extraction, ambiguity, source selection, and full/incremental cleanup. 4. Run focused and full project verification, then update the task for human review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Recovered bodies are parsed from the source HTML renderer's existing unresolved-CID placeholders. During the atomic derived-message rebuild, the canonical occurrence (lowest source NID, then quote position) supplies an attachment map built exclusively from its attachment rows. Duplicate normalized content IDs are intentionally omitted so they remain unresolved. CLEANER_VERSION is now 4 to invalidate pre-resolution caches.

Validation passed: uv run pytest tests/test_index.py (56 passed); uv run tox (Ruff, formatting, mypy, 125 tests, 100% coverage).
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @opencode
created: 2026-08-29 17:23
---
Agent: Implementation is ready for human review. This workflow has no review status, so the task remains In Progress pending human acceptance.
---

author: Human
created: 2026-08-29 17:28
---
Human: Confirmed the implementation works and authorized task closure.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Resolved quoted CID image placeholders during atomic derived-message rebuilding using only unique normalized content IDs from each recovered record's existing canonical source. The marker exposes the source attachment's already-valid extraction selector while recovered attachment listings and recovery provenance remain hidden. Added tests for normalized matching, extraction, missing metadata, duplicate CIDs, canonical-source isolation, and incremental/full synchronization. Verified with uv run pytest tests/test_index.py (56 passed) and uv run tox (Ruff, formatting, mypy, 125 tests, 100% coverage). No ADR or follow-up tasks created.
<!-- SECTION:FINAL_SUMMARY:END -->
