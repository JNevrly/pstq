---
id: TASK-006
title: Reconcile pypff dependency and install docs
status: Done
assignee:
  - '@opencode'
created_date: '2026-08-29 15:25'
updated_date: '2026-08-30 06:07'
labels:
  - code-review
  - packaging
dependencies: []
references:
  - README.md
modified_files:
  - README.md
  - pyproject.toml
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
- [x] #1 The README Installation section states the libpff/pypff prerequisite and a working install path
- [x] #2 pyproject.toml either declares the binding (as a dependency or documented extra) or the docs no longer imply plain pip install is sufficient
- [x] #3 Cosmetic blank lines in the pyproject classifiers and dependencies arrays are removed
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Document the devcontainer as the supported installation because libpff-python 20231205 supplies no Linux or CPython 3.13 wheel.
2. State that plain `pip install pstq` cannot provide the required native binding, and direct manual installations must build or provide a compatible `pypff` wheel.
3. Remove the extraneous blank lines from the project metadata arrays.
4. Validate the dependency lock, documentation commands, and full project checks.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Investigation: PyPI libpff-python 20231205 provides macOS x86_64 wheels only for CPython 3.8 through 3.12, plus a source distribution. The project targets Linux/Python 3.13, and the devcontainer builds the checksum-verified source release into pypff. Declaring libpff-python as a normal dependency would not make plain pip installation work in the supported environment.

Implementation: README now identifies pypff/libpff as a native prerequisite, makes the devcontainer the supported install path, and explains that plain pip installation cannot synchronize a cache. pyproject.toml metadata arrays no longer contain blank spacer lines.

Validation: uv lock --check, uv build, and uv run pstq --help passed. pytest ran 129 tests at 100% coverage. uv run tox was blocked only by an existing ruff format --check failure in untouched tests/test_index.py.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: @opencode
created: 2026-08-30 06:03
---
Agent: Implementation and acceptance criteria are ready for human review. The task remains In Progress because the project has no review status and only a human may accept it.
---

author: @human
created: 2026-08-30 06:07
---
Human: Reviewed the implementation and agreed to close the task.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Replaced the misleading standalone pip installation command with the supported devcontainer workflow and stated the native pypff/libpff prerequisite. The README explains that the upstream release has no Linux/Python 3.13 wheel and directs manual users to provide a compatible wheel using the devcontainer Dockerfile as the reference recipe. Removed spacer lines from pyproject.toml metadata arrays.

Validated with uv lock --check, uv build, and uv run pstq --help. pytest completed 129 tests at 100% coverage. uv run tox remains non-zero only because the pre-existing, untouched tests/test_index.py fails ruff format --check. No ADRs or follow-up tasks.
<!-- SECTION:FINAL_SUMMARY:END -->

Investigation: PyPI's libpff-python 20231205 release provides only macOS x86_64 wheels for CPython 3.8 through 3.12 plus a source distribution. The project targets Python 3.13 and its devcontainer already builds the checksum-verified source release into pypff. Declaring this package as a normal dependency would not make plain pip installation work on the supported Linux/Python 3.13 environment.
<!-- SECTION:NOTES:END -->

<!-- SECTION:NOTES:END -->
