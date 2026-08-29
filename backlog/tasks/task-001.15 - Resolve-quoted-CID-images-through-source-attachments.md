---
id: TASK-001.15
title: Resolve quoted CID images through source attachments
status: To Do
assignee:
  - '@opencode'
created_date: '2026-08-29 17:16'
labels: []
dependencies:
  - TASK-001.14
references:
  - docs/adr/0004-model-quoted-history-as-derived-messages.md
  - docs/adr/0005-unify-native-and-recovered-message-search.md
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
- [ ] #1 An exact normalized match between a quoted cid: image reference and the canonical source message attachment content_id renders as [attachment: ATTACHMENT_ID].
- [ ] #2 The emitted attachment ID works with the existing attachment ATTACHMENT_ID --output FILE command.
- [ ] #3 CID matching ignores case and surrounding angle brackets.
- [ ] #4 Missing or ambiguous CID matches remain [image: unresolved cid:...].
- [ ] #5 Matching is limited to the canonical source message and does not infer links from filename, content location, or unrelated attachments.
- [ ] #6 Ordinary native-message image rendering remains unchanged and recovery provenance remains absent from CLI output.
- [ ] #7 Full and incremental synchronization rebuild resolved markers atomically when source messages or attachments change.
- [ ] #8 Tests cover successful resolution, extraction ID validity, absent metadata, duplicate CID ambiguity, canonical-source selection, and synchronization cleanup.
<!-- AC:END -->
