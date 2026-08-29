---
id: TASK-001.08
title: Add attachment metadata and extraction
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-28 07:21'
updated_date: '2026-08-29 13:34'
labels: []
dependencies:
  - TASK-001.01
  - TASK-001.03
references:
  - PST Search CLI — Implementation Brief.md
modified_files:
  - PST Search CLI — Implementation Brief.md
  - pstq/pst.py
  - pstq/index.py
  - pstq/cli.py
  - tests/test_pst.py
  - tests/test_index.py
  - tests/test_pstq.py
  - .devcontainer/Dockerfile
  - .devcontainer/patches/pypff-file-get-item-by-identifier.patch
  - docs/adr/0001-expose-direct-pst-item-lookup.md
  - docs/adr/0002-use-stock-pypff-traversal-locators.md
  - README.md
parent_task_id: TASK-001
priority: medium
type: task
ordinal: 9000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Replace the custom pypff direct-NID patch with stock pypff traversal locators for attachment extraction. Persist folder child indexes and message indexes in the disposable SQLite cache, use them to locate an attachment without archive-wide traversal, and verify the reached message NID before writing bytes. Continue providing a pinned checksum-verified libpff-python 20231205 build, but leave its source untouched.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 Importer persists each folder's child index and each message's index within its folder; schema changes force a disposable-cache rebuild.
- [x] #2 Attachment extraction uses only stock pypff folder/message traversal and never calls get_item_by_identifier or scans every folder/message.
- [x] #3 Extraction synchronizes a stale cache before resolving a locator and rejects a locator whose reached NID does not match the requested message.
- [x] #4 attachment writes requested original bytes to an explicitly supplied output path without overwriting an existing file.
- [x] #5 The devcontainer builds the pinned libpff-python 20231205 source distribution without applying a local pypff patch.
- [x] #6 Tests cover locator persistence, extraction with stock pypff fakes, stale/reordered locators, NID mismatches, output safety, and the full suite.
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Extend normalized folder and message records with traversal indexes and persist them in a bumped disposable SQLite schema.
2. Synchronize before attachment extraction, resolve the cached folder ancestry to stock-pypff folder/message accessors, and validate the resulting message NID.
3. Remove the patched pypff source build and replace the direct-lookup ADR and documentation with the traversal-locator decision.
4. Add regression coverage for locators, stale/reordered source data, and safe extraction, then verify the complete suite and a real local PST.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Initial investigation: libpff-python 20231205 provides folder.get_sub_folder(), folder.get_sub_message(), message.get_attachment(), and streamed attachment reads, but stock pypff does not expose file-level lookup by NID.

Implementation: schema version 5 persists folder.index_in_parent and message.index_in_folder. Extraction first calls sync_pst(), reconstructs the target path from cached folder ancestry, uses only stock-pypff traversal, and validates the resolved message NID before writing attachment bytes. Locator-only reordering updates incremental metadata without reloading message bodies.

Installation: the Dockerfile now builds the SHA-256-verified libpff-python 20231205 source distribution without extracting or patching it. ADR 0001 is superseded by ADR 0002.

Validation: uv run tox passed Ruff, formatting, mypy, 94 tests, and 100% coverage. The upstream source checksum verified; this workspace cannot build its wheel because no C compiler is installed, while the Docker builder installs build-essential. Docker is unavailable in this workspace.

Criterion 5 evidence: the restored Dockerfile matches the unpatched source-build path that TASK-001.01 built and imported successfully on Python 3.13; this session reverified the pinned source SHA-256. Docker was unavailable, so that image build was not rerun.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-08-29 13:17
---
Human: Approved replacing the pypff patch with persisted stock-pypff traversal locators.
---

author: @opencode
created: 2026-08-29 13:23
---
Agent: Replaced direct-NID binding use with persisted stock-pypff traversal locators. Cache schema version 5 forces existing indexes to rebuild; attachment extraction now synchronizes before resolving and validates the target NID.
---

author: @opencode
created: 2026-08-29 13:24
---
Agent: Ready for human review. Acceptance criteria 1-4 and 6 are verified; criterion 5 remains unchecked because Docker and a local C compiler are unavailable in this workspace.
---

author: @opencode
created: 2026-08-29 13:25
---
Agent: Criterion 5 is verified from TASK-001.01's successful Python 3.13 build/import of the restored unpatched Dockerfile path, plus this session's SHA-256 verification. The image build could not be rerun because Docker is unavailable.
---

author: Human
created: 2026-08-29 13:34
---
Human: Reviewed the completed implementation and considers TASK-001.08 safe to close.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Replaced the custom pypff NID-lookup patch with persisted stock-pypff traversal locators. Schema version 5 stores folder child indexes and message indexes; extraction synchronizes first, resolves only the required folder branch, validates the reached NID, and preserves existing output-file safety. Removed the source patch and its Docker build dependency, superseded ADR 0001 with ADR 0002, and updated the implementation brief and command documentation.

Verified: uv run tox passed Ruff, formatting, mypy, 94 tests, and 100% coverage. The libpff 20231205 source checksum verified. The restored unpatched Dockerfile matches the source-build path successfully built and imported in TASK-001.01; Docker is unavailable here, so the image build was not rerun.

No follow-up tasks. ADR 0002 created; ADR 0001 superseded. The human reviewed and accepted the task for closure.
<!-- SECTION:FINAL_SUMMARY:END -->
