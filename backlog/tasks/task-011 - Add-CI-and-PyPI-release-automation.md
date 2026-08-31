---
id: TASK-011
title: Add CI and PyPI release automation
status: Done
assignee: []
created_date: '2026-08-31 08:50'
updated_date: '2026-08-31 12:01'
labels: []
dependencies: []
references:
  - 'https://github.com/JNevrly/pstq'
  - 'https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/'
modified_files:
  - .github/workflows/ci.yml
  - .github/workflows/release.yml
  - CHANGELOG.md
priority: high
type: chore
ordinal: 19000
---

## Description

<!-- SECTION:DESCRIPTION:BEGIN -->
Add GitHub Actions quality checks and a secure tag-driven release workflow for the public pstq repository. The release path must publish matching semantic-version tags to PyPI using Trusted Publishing and create a GitHub Release with the validated artifacts.
<!-- SECTION:DESCRIPTION:END -->

## Acceptance Criteria
<!-- AC:BEGIN -->
- [x] #1 CI runs the existing quality suite for pushes and pull requests targeting main
- [x] #2 Pushing an exact vX.Y.Z tag validates that it matches the package version and changelog, then builds and validates wheel and source distributions
- [x] #3 A separate least-privileged job publishes validated artifacts to PyPI through the pypi GitHub environment using OIDC
- [x] #4 A successful PyPI publication creates a GitHub Release with the built distributions attached
- [x] #5 Manual recovery for an already-published tag skips the entire PyPI environment job and creates the missing GitHub Release
<!-- AC:END -->

## Implementation Plan

<!-- SECTION:PLAN:BEGIN -->
1. Add SHA-pinned CI workflow for main pushes and pull requests that runs the existing tox quality suite.
2. Add a tag-driven release workflow that validates vX.Y.Z tags against project metadata and changelog, runs the quality suite, builds and smoke-tests distributions, and passes artifacts between least-privileged jobs.
3. Publish through PyPI Trusted Publishing in the protected pypi environment, then create a GitHub Release with generated notes and attached artifacts.
4. Verify the workflow YAML and the local quality, build, metadata, and isolated-wheel checks; prepare the task for human review.
<!-- SECTION:PLAN:END -->

## Implementation Notes

<!-- SECTION:NOTES:BEGIN -->
Implemented SHA-pinned CI and tag-driven release workflows. Releases validate the exact vX.Y.Z tag against pyproject metadata, pstq.__version__, and CHANGELOG.md; run quality and distribution checks; publish with PyPI Trusted Publishing; and attach the validated artifacts to a generated GitHub Release.

Recovery hardening: the GitHub Release job checks out the validated tag before gh release create --verify-tag. Manual recovery with skip_pypi skips the entire pypi-environment job and permits GitHub Release creation only after the build succeeds and publishing either succeeds or is intentionally skipped.

Verification: workflow YAML parsing and zizmor security checks passed. GitHub CI run 33389451287 passed. The successful release workflow run 33389514702 recovered v0.1.0 without re-publishing. PyPI and the GitHub Release both expose the wheel and source distribution with matching SHA-256 hashes.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-08-31 08:50
---
Human: Use the existing unpublished local v0.1.0 tag for the first public release by recreating it at the final release commit. Include both normal CI and release automation.
---

author: Human
created: 2026-08-31 11:20
---
Human: PyPI publishing for v0.1.0 completed, but GitHub Release creation failed because gh could not find a Git repository.
---

author: Human
created: 2026-08-31 11:56
---
Human: A manual recovery run dispatched from main with skip_pypi was rejected because main is not allowed to deploy to the tag-restricted pypi environment.
---

author: Human
created: 2026-08-31 12:01
---
Human: The corrected manual recovery workflow completed successfully and the release is confirmed; close this task.
---
<!-- COMMENTS:END -->

## Final Summary

<!-- SECTION:FINAL_SUMMARY:BEGIN -->
Added secure CI and PyPI release automation, then published pstq 0.1.0. Verified successful GitHub CI, PyPI Trusted Publishing, GitHub Release creation with wheel and sdist assets, and the manual recovery path for an already-published tag. No ADRs or follow-up tasks were created.
<!-- SECTION:FINAL_SUMMARY:END -->
