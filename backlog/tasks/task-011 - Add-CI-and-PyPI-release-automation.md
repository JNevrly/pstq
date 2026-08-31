---
id: TASK-011
title: Add CI and PyPI release automation
status: In Progress
assignee: []
created_date: '2026-08-31 08:50'
updated_date: '2026-08-31 10:10'
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
- [ ] #1 CI runs the existing quality suite for pushes and pull requests targeting main
- [ ] #2 Pushing an exact vX.Y.Z tag validates that it matches the package version and changelog, then builds and validates wheel and source distributions
- [ ] #3 A separate least-privileged job publishes validated artifacts to PyPI through the pypi GitHub environment using OIDC
- [ ] #4 A successful PyPI publication creates a GitHub Release with the built distributions attached
- [ ] #5 The release workflow supports manual recovery for an existing release tag
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
Added SHA-pinned CI and release workflows. CI targets main pushes and pull requests. Release validates exact vX.Y.Z tags, pyproject and module versions, and the changelog before quality checks, build, metadata validation, isolated-wheel smoke test, OIDC PyPI publication, and GitHub Release creation.

Verification: workflow YAML parsed successfully; zizmor reported no findings after disabling release-job dependency caching; git diff --check, uv build, Twine metadata validation, and isolated-wheel CLI smoke test passed. The release-version validation script was exercised locally for v0.1.0; pyproject metadata, pstq.__version__, and the changelog heading matched.

TASK-012 restored the quality baseline: the complete tox suite passes with 141 tests and 100% coverage. Next action: commit the workflows, merge the unrelated GitHub main history into the renamed local main branch, configure the pypi environment and pending Trusted Publisher, then recreate and push v0.1.0.

Updated CHANGELOG.md to record 2026-08-31 as the first public release date for version 0.1.0.
<!-- SECTION:NOTES:END -->

## Comments

<!-- COMMENTS:BEGIN -->
author: Human
created: 2026-08-31 08:50
---
Human: Use the existing unpublished local v0.1.0 tag for the first public release by recreating it at the final release commit. Include both normal CI and release automation.
---
<!-- COMMENTS:END -->
