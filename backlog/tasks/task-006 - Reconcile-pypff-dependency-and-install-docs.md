---
id: TASK-006
title: Reconcile pypff dependency and install docs
status: To Do
assignee: []
created_date: '2026-08-29 15:25'
labels:
  - code-review
  - packaging
dependencies: []
references:
  - README.md
priority: medium
type: enhancement
ordinal: 6000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
The tool cannot create or synchronize a cache without a working `pypff` / libpff
binding — `PstReader._load_pypff` imports it at runtime — yet `pypff` appears
nowhere in `pyproject.toml` dependencies and is not present in `uv.lock`. The
README nonetheless opens with `pip install pstq` as the installation method.

A user following the README would install a package that imports successfully
but fails the moment it touches a PST, raising "pypff is not installed. Rebuild
the devcontainer or install its pinned libpff wheel." The real installation
contract is "bring your own libpff wheel / use the devcontainer," which the
Installation section does not state.

Make the packaging and documentation tell one consistent story: either declare
the binding as a dependency/extra (if a usable wheel exists) or replace the
`pip install` instructions with the actual supported install path and state the
libpff prerequisite up front. While here, drop the stray blank lines left in the
`classifiers` and `dependencies` arrays of `pyproject.toml`.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [ ] #1 The README Installation section states the libpff/pypff prerequisite and a working install path
- [ ] #2 pyproject.toml either declares the binding (as a dependency or documented extra) or the docs no longer imply plain pip install is sufficient
- [ ] #3 Cosmetic blank lines in the pyproject classifiers and dependencies arrays are removed
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Determine whether a distributable libpff/pypff wheel is available for the target platform.
2. If yes, add it (or an optional extra) and lock it; if no, document the devcontainer/manual-wheel path as the supported install.
3. Rewrite the README Installation section to match, leading with the prerequisite.
4. Tidy the pyproject arrays.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
<!-- SECTION:NOTES:END -->
