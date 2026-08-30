---
id: TASK-010
title: Own and distribute the libpff integration
status: To Do
assignee: []
created_date: '2026-08-30 08:01'
updated_date: '2026-08-30 16:02'
labels:
  - native
  - packaging
  - architecture
dependencies: []
references:
  - docs/adr/0001-expose-direct-pst-item-lookup.md
  - docs/adr/0002-use-stock-pypff-traversal-locators.md
  - 'https://github.com/libyal/libpff/tree/20231205'
  - >-
    https://github.com/libyal/testdata/blob/c3631ff17ce4ae6798ed9abd065c6a67ad626bce/pst/outlook.pst
priority: high
type: feature
ordinal: 17000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Replace the externally supplied, incomplete pypff dependency with a private native extension distributed inside PSTQ. Future PSTQ releases will use LGPL-3.0-or-later, matching libpff. The extension will use pinned libpff 20231205 sources, expose the PSTQ-required reader surface including direct item lookup by NID and generic property access, and ship first as a self-contained Linux x86-64 CPython 3.13 wheel.

The migration must remain staged: prove the native wheel and real-PST behavior before switching PstReader, and preserve the existing pypff/traversal path until the replacement is validated. Once direct lookup is active, remove traversal locator persistence and rebuild the disposable cache with schema version 11.

Use the public libyal outlook.pst fixture, pinned and attributed under CC BY 4.0, for native integration testing. Existing fake-based tests remain responsible for malformed and unavailable-property behavior.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 Future PSTQ release artifacts and metadata consistently identify the project as LGPL-3.0-or-later and preserve required upstream notices
- [ ] #2 A self-contained Linux x86-64 CPython 3.13 PSTQ wheel installs and reads PST files without an external pypff or libpff installation
- [ ] #3 PstReader uses the private extension for the existing read-only traversal and property surface and retrieves attachments through direct message-NID lookup
- [ ] #4 Traversal locator fields and SQLite columns are removed, schema version 11 rebuilds old disposable caches, and source synchronization and store-identity safety remain intact
- [ ] #5 Native integration tests use the pinned, attributed libyal PST fixture and verify direct lookup and attachment bytes
- [ ] #6 The devcontainer, CI, README, CLI help, implementation brief, lock data, and packaging documentation describe and verify the new installation model
<!-- AC:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Development freeze (2026-08-30): work is paused on branch `task-010-native_extension` at the request of the human because the private native-extension implementation did not converge to a simple solution.

Completed foundations: TASK-010.01 relicensed future releases and recorded ADRs; TASK-010.02 vendored and verified the pinned real PST fixture; TASK-010.03 produced a checksum-verified static-libpff private-extension wheel foundation that imports in a clean environment without a top-level pypff or runtime libpff shared library.

Unresolved binding obstacle (TASK-010.04): the required complete reader surface is already implemented by upstream pypff, but stock pypff lacks direct NID lookup and generic property access. Manually compiling its wrapper sources bypassed generated internal libyal headers (for example libcerror.h). Switching to the configured upstream Makefile avoided those include paths but exposed a libtool limitation under --disable-shared-libs: the pypff module target pypff.la is rejected because it is not lib-prefixed, and the default target does not yield a usable private extension artifact. The attempted temporary private-module rename also still needs validation.

Potential resumption paths: use the upstream Python packaging entry point to obtain its intended module build mode, or apply a minimal temporary Makefile/libtool target-name patch before building wrapper objects. Either path must preserve the statically linked libpff requirement, rename the initializer to pstq._pff, avoid installing a top-level pypff package, then add and verify direct-NID lookup, generic property access, ownership/error handling, and fixture integration tests.

Current risk: the in-progress TASK-010.04 build-hook edits are experimental and do not currently produce a wheel; restore the verified TASK-010.03 build state or complete one of the above approaches before treating the branch as releasable.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-08-30 08:03
---
Approved the proposal to replace external pypff with a private self-contained libpff extension, re-license future releases under LGPL-3.0-or-later, use direct NID lookup, remove traversal locators with schema version 11, and vendor the pinned libyal outlook.pst fixture with CC BY 4.0 attribution.
---

author: Human
created: 2026-08-30 16:02
---
Development is frozen on branch task-010-native_extension because the native-extension work did not converge to a simple solution.
---
<!-- COMMENTS:END -->
