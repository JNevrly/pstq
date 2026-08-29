# PST Query

[![PyPI](https://img.shields.io/pypi/v/pstq.svg)](https://pypi.python.org/pypi/pstq)
[![CI](https://github.com/JNevrly/pstq/actions/workflows/ci.yml/badge.svg)](https://github.com/JNevrly/pstq/actions/workflows/ci.yml)

PST Query is an offline command-line tool for searching an Outlook PST archive.
It keeps a local SQLite cache with an FTS5 index so agents can locate concise
message candidates before retrieving a complete message.

The PST is opened read-only and remains authoritative. The SQLite index is a
disposable cache: delete it to force a complete rebuild. A working `pypff` /
libpff binding is required to create or synchronize the cache.

## Installation

```console
$ pip install pstq
```

## Configuration

Configure one PST and one SQLite cache path in YAML. The directory containing
`index_path` must already exist because cache builds use a sibling temporary
file before atomically replacing the index.

```yaml
archive:
  pst_path: /archives/mail.pst
  index_path: /var/cache/pstq/mail.sqlite
```

Pass the file to every command:

```console
$ pstq --config pstq.yaml status
```

Generate a commented configuration template with:

```console
$ pstq --get-config-template pstq.yaml
```

Onacol environment overrides are also supported:

```console
$ export PSTQ_ARCHIVE__PST_PATH=/archives/mail.pst
$ export PSTQ_ARCHIVE__INDEX_PATH=/var/cache/pstq/mail.sqlite
$ pstq status --json
```

## Workflow

Start by checking the cache and inspecting its folder paths:

```console
$ pstq --config pstq.yaml status --json
$ pstq --config pstq.yaml folders --json
```

`search` checks the configured PST's path, size, and modification time before
querying. If the source changed, it synchronizes the cache first; otherwise it
queries immediately. Results are capped at 20 by default and at 100 maximum.
They deliberately omit message bodies.

```console
$ pstq --config pstq.yaml search 'Capon calibration' --json
$ pstq --config pstq.yaml search invoice \
    --from 'Jane Doe' \
    --to accounting@example.com \
    --after 2025-01-01 \
    --before 2026-01-01 \
    --folder 'Top of Outlook data file/Projects' \
    --has-attachment \
    --limit 10 \
    --json
```

Search supports FTS5 query syntax. Quote punctuation-heavy or exact phrases,
and prefer the `--to` filter for recipient email addresses.

Each result has a stable `id` composed of the store UID and PST NID, for
example `edc4f1c4c743ad49a590c83842fd889f:2128196`. Search JSON includes
`id`, `date`, `from`, `to`, `subject`, `folder`, `snippet`, and `score`.
Pass the selected ID to `show` to retrieve the complete persisted message:

```console
$ pstq --config pstq.yaml show edc4f1c4c743ad49a590c83842fd889f:2128196 --json
```

`show` reads only SQLite. It does not open the PST when the cache is available.
The returned record includes the selected body representation, body format,
participants, folder, message headers, relationship metadata, and attachment
count.

## Available Commands

| Command | Purpose |
| --- | --- |
| `status [--json]` | Report source and cache metadata plus freshness. |
| `folders [--json]` | List indexed folder paths and stable IDs. |
| `search QUERY [filters] [--json]` | Synchronize when needed, then run a bounded FTS5 search. |
| `show MESSAGE_ID [--json]` | Retrieve one complete persisted message from SQLite. |

`search` filters are `--from`, `--to`, `--after`, `--before`, `--folder`,
`--has-attachment`, and `--limit`.

Thread reconstruction and attachment metadata/extraction are planned but are
not available yet.

## Development

Run all formatting, linting, type checking, and tests with:

```console
$ uv run tox
```

This project uses [Backlog.md](https://github.com/MrLesk/Backlog.md) for task
tracking. The workflow is documented in `AGENTS.md`.

Free software: MIT license.
