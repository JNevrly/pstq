---
id: TASK-001.12
title: Render HTML bodies with image markers
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-29 09:46'
updated_date: '2026-08-29 10:25'
labels: []
dependencies:
  - TASK-001.08
references:
  - PST Search CLI — Implementation Brief.md
modified_files:
  - pstq/index.py
  - tests/test_index.py
parent_task_id: TASK-001
priority: medium
type: enhancement
ordinal: 13000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Render HTML message bodies into compact agent-readable text while preserving image placement as stable, actionable attachment markers. Preserve raw bodies for --full, never embed image bytes in default output, and use only anonymous fixtures.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Default show returns readable rendered text without HTML tags for HTML source bodies
- [x] #2 Recognized Outlook quoted HTML is removed conservatively after rendering
- [x] #3 CID-backed images are represented in place by stable attachment markers resolvable through the attachment commands
- [x] #4 Remote, data-URI, and unresolved CID images remain descriptive bounded markers without embedded bytes
- [x] #5 FTS indexes rendered cleaned text and show --full retains the original source body and format
- [x] #6 Tests use only anonymous HTML, text, and image fixtures
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Render HTML bodies to readable text with the standard-library parser and preserve image placement as bounded metadata markers.
2. Resolve CID image references to persisted stable attachment IDs during indexing.
3. Apply existing conservative quote detection to rendered text, retain raw source for --full, and update body format metadata.
4. Cover anonymous HTML fixtures and verify full reindexing.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Task 001.08 now persists attachment Content-ID metadata and stable IDs. The renderer will consume PstMessage attachment metadata while indexing, so it does not read image bytes or depend on real PST content in tests.

Bumped CLEANER_VERSION to 2 so existing caches perform a full reindex. The standard-library HTMLParser drops script/style content, normalizes text, and emits no image bytes. CID lookup normalizes angle brackets and case, and produces `[attachment: store:nid:index]`; remote, data, absent, and unresolved sources retain bounded descriptive markers. `uv run tox` passed: 92 tests, 100% coverage.
<!-- SECTION:NOTES:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Rendered HTML source bodies into agent-readable cleaned text while retaining original raw HTML and source format. Inline CID images now resolve to stable attachment extraction IDs; unsafe or unavailable sources remain bounded markers. Full reindexing is forced through cleaner version 2. Verified with anonymous HTML/image fixtures and `uv run tox` (92 tests, 100% coverage).
<!-- SECTION:FINAL_SUMMARY:END -->
