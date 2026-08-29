---
name: pstq
description: Use when searching, retrieving, threading, or extracting content from an Outlook PST with pstq.
---

# PST Query

Use `pstq` rather than parsing the PST or SQLite database directly. The PST is
read-only and authoritative; the SQLite index is a disposable local cache.

Before issuing an unfamiliar command, read its canonical documentation:

```console
pstq --help
pstq <command> --help
```

Use `--json` for programmatic work. On success it writes deterministic JSON to
stdout. On failure it writes a JSON error envelope to stderr and returns a
non-zero exit code. Do not infer JSON fields, ID formats, limits, cache access,
or synchronization behavior from this skill; command-level `--help` defines
the current contract.

The normal retrieval sequence is `status`, `folders` when needed, bounded
`search`, then `show` for selected message IDs. Use `thread`, `attachments`,
and `attachment` only after reading their help. Never modify the configured
PST or assume it is safe to access while Outlook is writing it.
