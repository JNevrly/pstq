# PST Search CLI — Implementation Brief

## Goal

Create a Linux CLI tool that lets an AI agent efficiently search and retrieve email from an Outlook PST archive.

The PST is not modified concurrently with the CLI. Outlook runs periodically on another system or environment and updates/organizes the PST every few days. When the CLI accesses the PST, Outlook is not running.

The CLI should therefore maintain a local searchable index that automatically synchronizes with the PST when it changes.

Primary goals:

- fast full-text search over a potentially large PST;
- current results after the PST has been updated;
- incremental synchronization rather than full reindexing where possible;
- preservation of PST folder organization;
- good handling of Outlook reply chains and duplicated quoted messages;
- machine-readable JSON interface suitable for agent use;
- local/offline operation;
- PST remains the authoritative source.

---

# 1. High-Level Architecture

```text
archive.pst
    │
    │ read using libpff / pypff
    ▼
PST scanner
    │
    │ normalized message representation
    ▼
Synchronizer
    │
    ├── new message       → index
    ├── changed message   → reindex
    ├── moved message     → update folder
    ├── unchanged message → skip
    └── deleted message   → remove
    │
    ▼
SQLite
    │
    ├── normal relational tables
    └── FTS5 search index
    │
    ▼
pstq CLI
    │
    ▼
AI agent
```

The agent should normally never parse the PST directly. It interacts only with `pstq`.

---

# 2. Technology Choices

Recommended initial stack:

- Python
- `libpff` / `pypff` for PST access
- SQLite for metadata/storage
- SQLite FTS5 for full-text search
- standard JSON output for agent integration

Avoid introducing Elasticsearch, Meilisearch, vector databases, etc. initially.

FTS5 should be sufficient for most email searches because queries commonly involve:

- people's names;
- company names;
- project names;
- product names;
- dates;
- filenames;
- error messages;
- technical terms.

Semantic/vector search can be added later as a complementary search mode.

---

# 3. PST Change Detection

Store information about the indexed PST:

```text
path
size
mtime_ns
store_uid
last_sync
schema/index version
```

Before normal search operations, cheaply check whether the PST changed.

Conceptually:

```text
pstq search ...
    │
    ├── PST unchanged
    │      └── search immediately
    │
    └── PST changed
           └── synchronize index
                  └── search
```

Also expose explicit synchronization:

```bash
pstq sync
pstq sync --full
pstq status
```

The agent may explicitly call:

```bash
pstq sync && pstq search ...
```

but automatic freshness checking should normally make this unnecessary.

---

# 4. Message Identity

Do not identify messages primarily using:

- subject;
- timestamp;
- Internet `Message-ID`;
- body hash.

`pypff` exposes the PST-native item identifier:

```python
message.identifier
message.get_identifier()
```

This corresponds to the PST item's NID.

Use a composite identity:

```text
(PST store UID, message NID)
```

For example:

```text
<store-uid>:<nid>
```

The PST store identity should ideally come from the PST message-store RecordKey/provider UID rather than from the filename.

Database primary key conceptually:

```sql
PRIMARY KEY (store_uid, nid)
```

An important implementation task is to verify and encapsulate retrieval of the store UID from `pypff`.

---

# 5. Message Moves

Moving a message between folders inside the same PST should normally preserve the message's PST NID.

Therefore:

```text
Inbox/message NID 1234
```

becoming:

```text
Projects/Foo/message NID 1234
```

should be treated as:

```sql
UPDATE message SET folder_id = ...
```

rather than:

```text
DELETE old message
INSERT new message
```

This is particularly important because normal Outlook organization frequently consists of moving messages from Inbox into archive/project folders.

Moving/copying between different PST stores should be treated as a different store identity.

---

# 6. Incremental Synchronization

Do not initially attempt low-level PST block-delta processing.

Instead perform a relatively cheap metadata scan of the PST after it changes.

For every message collect at least:

```text
store_uid
nid
folder_nid
modification_time
```

Compare that with the SQLite index.

Conceptual algorithm:

```python
generation += 1

for folder in walk_pst():
    for msg in folder.messages:
        key = (store_uid, msg.identifier)

        existing = db.lookup(key)

        if existing is None:
            index_full_message(msg)

        elif existing.modification_time != msg.modification_time:
            reindex_full_message(msg)

        elif existing.folder_nid != folder.identifier:
            update_folder(msg)

        mark_seen(key, generation)

delete_messages_not_seen_in(generation)
```

Thus:

```text
same NID + same mtime + same folder
    → skip

same NID + same mtime + different folder
    → folder move only

same NID + changed mtime
    → re-read/re-index message

new NID
    → insert/index

previously indexed NID not found
    → delete
```

Treat incremental synchronization as an optimization.

Always retain:

```bash
pstq sync --full
```

as a reliable recovery mechanism.

---

# 7. Initial Performance Test

Before implementing sophisticated synchronization, create a small benchmark that:

1. opens the actual PST;
2. recursively enumerates all folders;
3. enumerates all messages;
4. reads only:
   - message NID;
   - modification timestamp;
   - folder NID;
5. does NOT read bodies or attachments.

Measure total traversal time.

This determines whether metadata scanning is cheap enough for automatic synchronization.

Do this early in development.

---

# 8. Suggested Database Structure

Conceptually:

```text
pst_store
---------
uid
path
size
mtime_ns
last_sync


folder
------
store_uid
nid
parent_nid
name
path


message
-------
store_uid
nid
folder_nid

internet_message_id
in_reply_to
references

conversation_topic
conversation_index

subject

sender_name
sender_email

sent_at
received_at
modification_time

body_raw
body_clean

has_attachments


recipient
---------
store_uid
message_nid
type        # to / cc / bcc
name
email


attachment
----------
id
store_uid
message_nid
index_in_message
filename
mime_type
size
extracted_text
```

And an FTS5 table for searchable content.

Exact normalization can evolve during implementation.

---

# 9. Outlook Reply-Chain Duplication

Outlook replies often contain previous messages inside the body.

Example:

```text
Message A:
A

Message B:
B
--- previous message ---
A

Message C:
C
--- previous message ---
B
A
```

Naively indexing complete bodies causes:

- duplicate search hits;
- distorted ranking;
- poor snippets;
- unnecessary index size;
- confusion for the agent.

This should be treated as a core indexing requirement.

---

# 10. Raw Body vs Clean Body

Store two body representations:

```text
body_raw
body_clean
```

`body_raw`:

- exact or minimally normalized body extracted from PST;
- preserved for display/retrieval;
- never destructively modified.

`body_clean`:

- best-effort extraction of content authored in this particular email;
- quoted previous correspondence removed;
- signature/disclaimer removal may later be added;
- used for normal full-text indexing.

Default FTS should index `body_clean`, not `body_raw`.

---

# 11. Quote Removal

Start with conservative heuristics.

Common separators include constructs such as:

```text
-----Original Message-----
```

or Outlook-style header blocks:

```text
From:
Sent:
To:
Cc:
Subject:
```

HTML Outlook messages may also contain recognizable structures/classes.

The algorithm should strongly prefer false negatives over false positives:

```text
uncertain whether text is quoted
    → KEEP IT

certain text is quoted history
    → remove from body_clean
```

It is better to retain some duplicated text than to remove genuine authored content.

Never modify `body_raw`.

---

# 12. Future Cross-Message Deduplication

A possible later improvement is archive-aware deduplication.

Normalize message text into paragraphs/blocks and hash them.

Example:

```text
Mail 1: [AAAA]
Mail 2: [BBBB][AAAA]
Mail 3: [CCCC][BBBB][AAAA]
```

could yield searchable authored content:

```text
Mail 1 → [AAAA]
Mail 2 → [BBBB]
Mail 3 → [CCCC]
```

This can detect quoted content even when mail clients do not use standard separators.

Do NOT make this a requirement for the first implementation.

Design `body_clean` generation as a replaceable indexing stage so this can be introduced later and followed by a reindex.

---

# 13. Signatures and Disclaimers

Corporate email can contain extremely repetitive signatures and confidentiality notices.

Longer term, body processing can conceptually classify:

```text
raw body
    │
    ├── authored content       ← index
    ├── signature
    ├── disclaimer
    └── quoted correspondence
```

Signature/disclaimer removal is useful but lower priority than quoted-history removal.

Again, retain `body_raw`.

---

# 14. Threading

Store available email relationship metadata:

```text
Internet Message-ID
In-Reply-To
References
ConversationTopic
ConversationIndex
```

This supports an agent-facing command such as:

```bash
pstq thread <message-id>
```

The ideal result is a chronological list of individual contributions rather than one giant Outlook body containing the entire conversation repeatedly.

Example:

```text
2026-03-01 John   Initial proposal
2026-03-02 Josef  Alternative suggested
2026-03-02 John   Clarification
2026-03-03 Josef  Final decision
```

Thread reconstruction should be independent of quote stripping.

---

# 15. FTS Index

Normal search should cover approximately:

```text
subject
sender
recipient names/emails
body_clean
attachment extracted text
possibly filename
```

Folder path should normally be a structured filter rather than important ranking text.

Use FTS5 ranking, likely BM25.

Provide structured filtering through normal SQL.

Examples:

```bash
pstq search "Capon calibration"

pstq search "invoice" \
    --from john@example.com \
    --after 2025-01-01

pstq search '"AWS organization"' \
    --folder "Projects/0M"

pstq search "ICDS" \
    --has-attachment
```

---

# 16. Search Result Design

Search should return lightweight results.

For agent use, JSON should resemble:

```json
[
  {
    "id": "<stable-cli-id>",
    "date": "2026-08-20T12:32:11+02:00",
    "from": "person@example.com",
    "to": ["other@example.com"],
    "subject": "Example subject",
    "folder": "Projects/Foo",
    "snippet": "Relevant matching text...",
    "score": 9.42
  }
]
```

Do NOT return full bodies from `search`.

The agent first finds candidates, then explicitly retrieves relevant messages.

This minimizes agent context/token consumption.

---

# 17. Suggested CLI

Keep the agent-facing interface small.

Minimum useful commands:

```bash
pstq status

pstq sync
pstq sync --full

pstq folders

pstq search QUERY [filters...] [--json]

pstq show MESSAGE_ID [--json]

pstq thread MESSAGE_ID [--json]

pstq attachments MESSAGE_ID [--json]

pstq attachment ATTACHMENT_ID --output FILE
```

Useful search filters:

```text
--from
--to
--after
--before
--folder
--has-attachment
--limit
--json
```

Potential later option:

```bash
pstq search QUERY --include-quotes
```

which searches `body_raw` when normal cleaned-body search is insufficient.

---

# 18. Agent Interface Philosophy

Optimize the CLI for iterative retrieval:

```text
1. search
2. inspect lightweight results
3. show selected message
4. optionally retrieve thread
5. optionally retrieve attachment
```

Avoid APIs that dump thousands of emails or complete threads into the model context.

JSON output should be deterministic and easy to parse.

Human-readable output is useful but secondary.

---

# 19. Attachments

Initially store:

```text
filename
mime type
size
message relationship
optional extracted text
```

Do not necessarily duplicate attachment binary data into SQLite or an object store.

Since Outlook is not running while the agent accesses the PST, original attachment bytes can be extracted from the PST on demand.

Potential flow:

```bash
pstq attachments <message>
pstq attachment <attachment-id> --output /tmp/report.pdf
```

Attachment full-text extraction can be added separately.

Possible formats worth supporting eventually:

- PDF
- DOCX
- XLSX
- PPTX
- TXT
- HTML

Attachment indexing should be separable from basic email indexing because it can be significantly more expensive.

---

# 20. pypff Direct Lookup Limitation

The underlying libpff C API provides lookup of an item by identifier/NID.

Current `pypff` should be checked because its Python wrapper may not expose the equivalent direct `get_item_by_identifier()` method.

If the binding does not expose it, preferred solution:

> add a very small Python binding exposing the existing libpff item-by-NID lookup.

This would allow:

```text
CLI message ID
    ↓
(store UID, NID)
    ↓
direct PST item lookup
```

which is particularly useful for retrieving attachment bytes.

Do not work around this permanently by traversing the entire PST for every `show`/attachment operation.

During development, verify the current pypff API/version before implementing the extension.

---

# 21. What Should Be Stored in SQLite?

Store enough data that ordinary operations require no PST access:

```text
search
show
thread reconstruction
folder browsing
attachment metadata
```

Thus message bodies should live in SQLite.

The PST should normally only be reopened for:

- synchronization;
- retrieving original attachment bytes;
- possibly retrieving unusual properties not persisted in SQLite.

This makes agent operations fast.

---

# 22. Reindexability

The PST is authoritative.

SQLite is disposable.

The following must always be valid:

```bash
rm index.sqlite
pstq sync --full
```

Therefore avoid storing important user-generated state solely in the index.

Schema upgrades and improved body-cleaning algorithms can simply trigger a full reindex.

---

# 23. Error/Safety Model

The PST access layer should be strictly read-only.

The tool must never modify the PST.

Check for obvious signs that the PST might currently be in use where possible, and fail conservatively rather than risking corruption.

SQLite/index corruption should never threaten the PST.

---

# 24. Suggested Development Order

Implement approximately in this order:

### Phase 1 — PST exploration

Create diagnostic code that:

- opens PST;
- obtains store identity;
- recursively traverses folders;
- enumerates messages;
- prints:
  - NID;
  - folder NID/path;
  - modification time;
  - subject.

Measure traversal performance on the real PST.

### Phase 2 — Basic SQLite importer

Implement:

```text
PST → normalized message → SQLite
```

Store metadata plus raw body.

### Phase 3 — Incremental synchronization

Implement:

```text
new
changed
moved
deleted
unchanged
```

using `(store UID, NID)` identity.

### Phase 4 — FTS5

Add FTS indexing and:

```bash
pstq search
pstq show
```

### Phase 5 — Body cleaning

Implement conservative Outlook quoted-history removal.

Store:

```text
body_raw
body_clean
```

Index only `body_clean`.

### Phase 6 — Thread reconstruction

Use mail headers plus Outlook conversation metadata.

Implement:

```bash
pstq thread
```

### Phase 7 — Attachments

Implement metadata listing and extraction.

Add attachment text indexing separately.

### Phase 8 — Agent ergonomics

Finalize:

- JSON schema;
- stable IDs;
- search limits;
- snippets;
- errors;
- exit codes.

Only after the above should semantic/vector search or sophisticated cross-message deduplication be considered.

---

# 25. Important Design Principles

1. **PST is authoritative; SQLite is a cache/index.**
2. **Never modify the PST.**
3. **Use PST-native identities rather than heuristics whenever possible.**
4. **Re-scan metadata; don't try to reverse-engineer PST filesystem deltas.**
5. **Avoid re-reading bodies of unchanged messages.**
6. **Keep original and cleaned bodies separately.**
7. **Index authored content rather than repeated Outlook history.**
8. **Prefer conservative quote removal.**
9. **Return small search results and fetch full messages separately.**
10. **Design everything so a full reindex is always possible.**
11. **Start with lexical FTS; semantic search is an optional later layer.**
12. **Benchmark the actual PST before optimizing further.**

## First Development Milestone

The first useful milestone should be a program roughly equivalent to:

```bash
pstq inspect archive.pst
```

which reports:

```text
PST store UID
PST size
number of folders
number of messages
metadata traversal time

sample messages:
  NID
  folder NID/path
  modification time
  subject
```

This validates the three assumptions on which the rest of the design depends:

1. stable usable PST-native message IDs are exposed;
2. the PST store identity can be obtained;
3. metadata traversal of the real archive is fast enough for incremental synchronization.

Do this before building the search/index layer.