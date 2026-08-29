"""Disposable SQLite cache creation and atomic incremental synchronization."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from base64 import b64decode
from binascii import Error as BinasciiError
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email import policy
from email.parser import HeaderParser
from email.utils import getaddresses
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast

from pstq.body import (
    ANALYZER_VERSION,
    QuotedMessage,
    analyze_body,
    is_owner,
    native_fingerprint,
)
from pstq.pst import PstAttachment, PstFolder, PstMessage, PstReader

SCHEMA_VERSION = 9
CLEANER_VERSION = 3

_ORIGINAL_MESSAGE_SEPARATOR = re.compile(
    r"^-----Original Message-----\s*$", re.IGNORECASE
)
_MESSAGE_ID = re.compile(r"<[^<>\s@]+@[^<>\s@]+>")
_HTML_BLOCK_TAGS = frozenset(
    {"address", "blockquote", "br", "div", "hr", "li", "p", "pre", "tr"}
)


class _HtmlBodyRenderer(HTMLParser):
    """Convert message HTML to bounded text without fetching external resources."""

    def __init__(self, attachment_ids: dict[str, str]) -> None:
        super().__init__(convert_charrefs=True)
        self._attachment_ids = attachment_ids
        self._parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag in _HTML_BLOCK_TAGS:
            self._newline()
        if tag == "img":
            self._parts.append(
                _image_marker(dict(attrs).get("src"), self._attachment_ids)
            )

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and tag in _HTML_BLOCK_TAGS:
            self._newline()

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._parts.append(data)

    def _newline(self) -> None:
        if self._parts and not self._parts[-1].endswith("\n"):
            self._parts.append("\n")

    def rendered(self) -> str:
        return "\n".join(
            " ".join(line.split()) for line in "".join(self._parts).splitlines()
        ).strip()


class PstSynchronizationError(RuntimeError):
    """Raised when a PST changes while its cache is being synchronized."""


@dataclass(frozen=True)
class ImportResult:
    """Counts written by one successful full cache import."""

    store_uid: str
    folder_count: int
    message_count: int


@dataclass(frozen=True)
class SyncResult:
    """The outcome of a synchronization attempt."""

    store_uid: str
    folder_count: int
    message_count: int
    new_count: int
    modified_count: int
    moved_count: int
    deleted_count: int
    skipped: bool
    full: bool


@dataclass(frozen=True)
class SearchResult:
    """A lightweight indexed message match suitable for search output."""

    id: str
    date: str | None
    sender: str | None
    recipients: tuple[str, ...]
    subject: str | None
    folder: str
    snippet: str
    score: float

    def as_dict(self) -> dict[str, object]:
        return {
            "date": self.date,
            "folder": self.folder,
            "from": self.sender,
            "id": self.id,
            "score": self.score,
            "snippet": self.snippet,
            "subject": self.subject,
            "to": list(self.recipients),
        }


@dataclass(frozen=True)
class _SourceState:
    path: str
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class _IndexState:
    source: _SourceState
    store_uid: str
    schema_version: int
    cleaner_version: int
    generation: int
    history_fingerprint: str = ""


@dataclass(frozen=True)
class HistorySettings:
    """Explicit archive-owner context for quoted-history recovery."""

    owner_emails: tuple[str, ...] = ()
    owner_names: tuple[str, ...] = ()
    timezone: str = "UTC"

    @property
    def enabled(self) -> bool:
        return bool(self.owner_emails or self.owner_names)


DEFAULT_HISTORY_SETTINGS = HistorySettings()


def import_pst(
    source_path: str | Path,
    database_path: str | Path,
    history: HistorySettings = DEFAULT_HISTORY_SETTINGS,
) -> ImportResult:
    """Build DATABASE_PATH from SOURCE_PATH without risking its current contents."""
    source = _source_state(source_path)
    target = Path(database_path)
    temporary_path = _temporary_database_path(target)
    try:
        result = _write_index(source_path, temporary_path, source, history)
        os.replace(temporary_path, target)
        return result
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def sync_pst(
    source_path: str | Path,
    database_path: str | Path,
    history: HistorySettings = DEFAULT_HISTORY_SETTINGS,
    *,
    full: bool = False,
) -> SyncResult:
    """Synchronize DATABASE_PATH with SOURCE_PATH without replacing a usable cache.

    The normal path scans only metadata, then reads bodies solely for new or
    modified messages.  All changes are made to a temporary database and
    atomically swapped into place only after the source is verified unchanged.
    """
    target = Path(database_path)
    if full or not target.is_file():
        return _full_sync(source_path, target, history)

    state = _read_index_state(target)
    if (
        state is None
        or state.schema_version != SCHEMA_VERSION
        or state.cleaner_version != CLEANER_VERSION
        or state.history_fingerprint != _history_fingerprint(history)
    ):
        return _full_sync(source_path, target, history)

    source = _source_state(source_path)
    if source == state.source:
        folder_count, message_count = _cache_counts(target, state.store_uid)
        return SyncResult(
            state.store_uid,
            folder_count,
            message_count,
            new_count=0,
            modified_count=0,
            moved_count=0,
            deleted_count=0,
            skipped=True,
            full=False,
        )

    result = _incremental_sync(source_path, target, source, state, history)
    return result if result is not None else _full_sync(source_path, target, history)


def index_status(
    source_path: str | Path,
    database_path: str | Path,
    history: HistorySettings = DEFAULT_HISTORY_SETTINGS,
) -> dict[str, object]:
    """Return source and cache metadata without opening the PST reader."""
    source_path = str(Path(source_path).resolve())
    database_path = str(Path(database_path).resolve())
    state, last_successful_sync = _read_status_state(Path(database_path))
    try:
        source = _source_state(source_path)
    except OSError as error:
        source = None
        source_error: str | None = str(error)
    else:
        source_error = None
    return {
        "fresh": (
            source is not None
            and state is not None
            and state.schema_version == SCHEMA_VERSION
            and state.cleaner_version == CLEANER_VERSION
            and state.history_fingerprint == _history_fingerprint(history)
            and state.source == source
        ),
        "index_exists": Path(database_path).is_file(),
        "index_path": database_path,
        "last_successful_sync": last_successful_sync,
        "schema_version": state.schema_version if state else None,
        "cleaner_version": state.cleaner_version if state else None,
        "source_error": source_error,
        "source_mtime_ns": source.mtime_ns if source else None,
        "source_path": source_path,
        "source_size": source.size if source else None,
        "store_uid": state.store_uid if state else None,
    }


def list_folders(database_path: str | Path) -> list[dict[str, object]]:
    """List stable folder identifiers and paths from the current cache."""
    state = _require_index_state(database_path)
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT nid, parent_nid, name, path
            FROM folder
            WHERE store_uid = ?
            ORDER BY path, nid
            """,
            (state.store_uid,),
        ).fetchall()
    return [
        {
            "id": _record_id(state.store_uid, row[0]),
            "name": row[2],
            "parent_id": (
                _record_id(state.store_uid, row[1]) if row[1] is not None else None
            ),
            "path": row[3],
        }
        for row in rows
    ]


def search_messages(
    database_path: str | Path,
    query: str,
    *,
    sender: str | None = None,
    sender_aliases: Sequence[str] = (),
    recipient: str | None = None,
    after: str | None = None,
    before: str | None = None,
    folder: str | None = None,
    has_attachment: bool = False,
    limit: int = 20,
) -> list[SearchResult]:
    """Search native and recovered messages with FTS5 and structured filters."""
    if not query.strip():
        raise ValueError("Search query must not be empty.")
    state = _require_index_state(database_path)
    filters = ["search_fts MATCH ?", "search_document.store_uid = ?"]
    parameters: list[object] = [query, state.store_uid]
    if sender:
        filters.append("search_document.sender LIKE ? COLLATE NOCASE")
        parameters.append(f"%{sender}%")
    aliases = tuple(alias for alias in sender_aliases if alias.strip())
    if aliases:
        filters.append(
            "("
            + " OR ".join(
                "search_document.sender_aliases LIKE ? COLLATE NOCASE" for _ in aliases
            )
            + ")"
        )
        parameters.extend(f"%{alias}%" for alias in aliases)
    if recipient:
        filters.append("search_document.recipients_text LIKE ? COLLATE NOCASE")
        parameters.append(f"%{recipient}%")
    if after:
        filters.append("search_document.date >= ?")
        parameters.append(after)
    if before:
        filters.append("search_document.date < ?")
        parameters.append(before)
    if folder:
        filters.append("search_document.folder_path = ?")
        parameters.append(folder)
    if has_attachment:
        filters.append("search_document.has_attachment = 1")

    statement = f"""
        SELECT search_document.selector, search_document.subject,
               search_document.sender, search_document.date,
               search_document.folder_path, search_document.recipients_json,
               snippet(search_fts, -1, '', '', '...', 20), -bm25(search_fts)
        FROM search_fts
        JOIN search_document ON search_document.rowid = search_fts.rowid
        WHERE {" AND ".join(filters)}
        ORDER BY bm25(search_fts), search_document.selector
        LIMIT ?
    """
    parameters.append(limit)
    try:
        with sqlite3.connect(database_path) as connection:
            connection.text_factory = _decode_sqlite_text
            rows = connection.execute(statement, parameters).fetchall()
    except sqlite3.OperationalError as error:
        if any(
            value in str(error).lower()
            for value in ("fts5", "syntax error", "unterminated string")
        ):
            raise ValueError(f"Invalid FTS query: {query}") from error
        raise
    return [
        SearchResult(
            id=_sqlite_optional_text(row[0]) or "",
            subject=row[1],
            sender=row[2],
            date=row[3],
            folder=row[4],
            snippet=row[6] or "",
            score=row[7],
            recipients=tuple(json.loads(_sqlite_optional_text(row[5]) or "[]")),
        )
        for row in rows
    ]


def get_message(
    database_path: str | Path, message_id: str, *, full: bool = False
) -> dict[str, object]:
    """Return a persisted message with its cleaned body unless FULL is requested."""
    state = _require_index_state(database_path)
    recovered = _parse_recovered_record_id(message_id)
    if recovered is not None:
        store_uid, fingerprint = recovered
        if store_uid != state.store_uid:
            raise ValueError(f"Message ID does not belong to this index: {message_id}")
        with sqlite3.connect(database_path) as connection:
            connection.text_factory = _decode_sqlite_text
            row = connection.execute(
                """
                SELECT recovered_message.sender, recovered_message.recipients_json,
                       recovered_message.subject, recovered_message.sent_at,
                       recovered_message.body, search_document.folder_nid,
                       search_document.folder_path
                FROM recovered_message
                JOIN search_document
                  ON search_document.store_uid = recovered_message.store_uid
                 AND search_document.recovered_fingerprint
                     = recovered_message.fingerprint
                WHERE recovered_message.store_uid = ?
                  AND recovered_message.fingerprint = ?
                """,
                (store_uid, fingerprint),
            ).fetchone()
        if row is None:
            raise ValueError(f"Message not found: {message_id}")
        return _recovered_message_record(store_uid, fingerprint, row)

    store_uid, nid = _parse_record_id(message_id)
    if store_uid != state.store_uid:
        raise ValueError(f"Message ID does not belong to this index: {message_id}")
    with sqlite3.connect(database_path) as connection:
        connection.text_factory = _decode_sqlite_text
        row = connection.execute(
            """
            SELECT message.nid, message.folder_nid, message.modification_time,
                   message.subject, message.sender_name, message.client_submit_time,
                   message.delivery_time, message.transport_headers,
                   message.internet_message_id, message.in_reply_to,
                   message.references_header, message.conversation_topic,
                   message.conversation_index, message.attachment_count,
                   message.body_raw, message.body_clean, message.body_format,
                   folder.path
            FROM message
            JOIN folder ON folder.store_uid = message.store_uid
                       AND folder.nid = message.folder_nid
            WHERE message.store_uid = ? AND message.nid = ?
            """,
            (store_uid, nid),
        ).fetchone()
        if row is None:
            raise ValueError(f"Message not found: {message_id}")
        recipients = _recipients_for_messages(connection, store_uid, ((nid,),))[nid]
    return _message_record(store_uid, row, recipients, full=full)


def get_thread(database_path: str | Path, message_id: str) -> dict[str, object]:
    """Return related persisted messages without opening the source PST."""
    state = _require_index_state(database_path)
    recovered = _parse_recovered_record_id(message_id)
    if recovered is not None:
        store_uid, fingerprint = recovered
    else:
        store_uid, anchor_nid = _parse_record_id(message_id)
    if store_uid != state.store_uid:
        raise ValueError(f"Message ID does not belong to this index: {message_id}")
    with sqlite3.connect(database_path) as connection:
        connection.text_factory = _decode_sqlite_text
        if recovered is not None:
            anchor = connection.execute(
                """
                SELECT canonical_source_nid FROM search_document
                WHERE store_uid = ? AND recovered_fingerprint = ?
                """,
                (store_uid, fingerprint),
            ).fetchone()
            if anchor is None:
                raise ValueError(f"Message not found: {message_id}")
            anchor_nid = cast(int, anchor[0])
        relationship_rows = connection.execute(
            """
            SELECT nid, internet_message_id, in_reply_to, references_header,
                   conversation_topic, conversation_index
            FROM message
            WHERE store_uid = ?
            """,
            (store_uid,),
        ).fetchall()
        if not any(row[0] == anchor_nid for row in relationship_rows):
            raise ValueError(f"Message not found: {message_id}")
        nids = _thread_members(relationship_rows, anchor_nid)
        placeholders = ", ".join("?" for _ in nids)
        rows = connection.execute(
            f"""
            SELECT message.nid, message.folder_nid, message.modification_time,
                   message.subject, message.sender_name, message.client_submit_time,
                   message.delivery_time, message.transport_headers,
                   message.internet_message_id, message.in_reply_to,
                   message.references_header, message.conversation_topic,
                   message.conversation_index, message.attachment_count,
                   message.body_raw, message.body_clean, message.body_format,
                   folder.path
            FROM message
            JOIN folder ON folder.store_uid = message.store_uid
                       AND folder.nid = message.folder_nid
            WHERE message.store_uid = ? AND message.nid IN ({placeholders})
            """,
            (store_uid, *nids),
        ).fetchall()
        recipients = _recipients_for_messages(
            connection, store_uid, tuple((row[0],) for row in rows)
        )
        recovered_rows = connection.execute(
            f"""
            SELECT recovered_message.fingerprint, recovered_message.sender,
                    recovered_message.recipients_json, recovered_message.subject,
                    recovered_message.sent_at, recovered_message.body,
                    search_document.folder_nid, search_document.folder_path
            FROM recovered_message
            JOIN search_document
              ON search_document.store_uid = recovered_message.store_uid
             AND search_document.recovered_fingerprint = recovered_message.fingerprint
            WHERE recovered_message.store_uid = ?
              AND EXISTS (
                  SELECT 1 FROM quote_occurrence
                  WHERE quote_occurrence.store_uid = recovered_message.store_uid
                    AND quote_occurrence.recovered_fingerprint
                        = recovered_message.fingerprint
                    AND quote_occurrence.source_message_nid IN ({placeholders})
              )
            ORDER BY recovered_message.fingerprint
            """,
            (store_uid, *nids),
        ).fetchall()
    records = [_message_record(store_uid, row, recipients[row[0]]) for row in rows]
    records.extend(_recovered_message_records(store_uid, recovered_rows))
    records.sort(key=_record_order)
    return {
        "id": message_id,
        "messages": records,
    }


def _message_record(
    store_uid: str,
    row: Sequence[object],
    recipients: Sequence[str],
    *,
    full: bool = False,
) -> dict[str, object]:
    """Normalize one SQLite message row for command output."""
    return {
        "attachment_count": row[13],
        "body": _sqlite_optional_text(row[14] if full else row[15]),
        "body_format": _sqlite_optional_text(row[16]),
        "client_submit_time": _sqlite_optional_text(row[5]),
        "conversation_index": _sqlite_optional_text(row[12]),
        "conversation_topic": _sqlite_optional_text(row[11]),
        "date": _sqlite_optional_text(row[6] or row[5]),
        "delivery_time": _sqlite_optional_text(row[6]),
        "folder": _sqlite_optional_text(row[17]),
        "folder_id": _record_id(store_uid, cast(int, row[1])),
        "from": _sqlite_optional_text(row[4]),
        "id": _record_id(store_uid, cast(int, row[0])),
        "in_reply_to": _sqlite_optional_text(row[9]),
        "internet_message_id": _sqlite_optional_text(row[8]),
        "modification_time": _sqlite_optional_text(row[2]),
        "references": _sqlite_optional_text(row[10]),
        "subject": _sqlite_optional_text(row[3]),
        "to": list(recipients),
        "transport_headers": _sqlite_optional_text(row[7]),
    }


def list_attachments(
    database_path: str | Path, message_id: str
) -> list[dict[str, object]]:
    """Return persisted attachment metadata without opening the source PST."""
    state = _require_index_state(database_path)
    recovered = _parse_recovered_record_id(message_id)
    if recovered is not None:
        store_uid, _ = recovered
        if store_uid != state.store_uid:
            raise ValueError(f"Message ID does not belong to this index: {message_id}")
        return []
    store_uid, message_nid = _parse_record_id(message_id)
    if store_uid != state.store_uid:
        raise ValueError(f"Message ID does not belong to this index: {message_id}")
    with sqlite3.connect(database_path) as connection:
        rows = connection.execute(
            """
            SELECT index_in_message, filename, mime_type, size, content_id,
                   content_location, attachment_method, hidden, rendering_position
            FROM attachment
            WHERE store_uid = ? AND message_nid = ?
            ORDER BY index_in_message
            """,
            (store_uid, message_nid),
        ).fetchall()
    return [
        {
            "attachment_method": row[6],
            "content_id": _sqlite_optional_text(row[4]),
            "content_location": _sqlite_optional_text(row[5]),
            "filename": _sqlite_optional_text(row[1]),
            "hidden": bool(row[7]) if row[7] is not None else None,
            "id": _attachment_id(store_uid, message_nid, row[0]),
            "mime_type": _sqlite_optional_text(row[2]),
            "rendering_position": row[8],
            "size": row[3],
        }
        for row in rows
    ]


def extract_attachment(
    source_path: str | Path,
    database_path: str | Path,
    attachment_id: str,
    output_path: str | Path,
    history: HistorySettings = DEFAULT_HISTORY_SETTINGS,
) -> int:
    """Extract one persisted attachment through a cached traversal locator."""
    store_uid, message_nid, attachment_index = _parse_attachment_id(attachment_id)
    sync_pst(source_path, database_path, history)
    state = _require_index_state(database_path)
    if store_uid != state.store_uid:
        raise ValueError(
            f"Attachment ID does not belong to this index: {attachment_id}"
        )
    with sqlite3.connect(database_path) as connection:
        exists = connection.execute(
            """
            SELECT 1 FROM attachment
            WHERE store_uid = ? AND message_nid = ? AND index_in_message = ?
            """,
            (store_uid, message_nid, attachment_index),
        ).fetchone()
    if exists is None:
        raise ValueError(f"Attachment not found: {attachment_id}")
    with PstReader(source_path) as reader:
        if reader.store.uid != state.store_uid:
            raise PstSynchronizationError("PST store does not match this index.")
        with sqlite3.connect(database_path) as connection:
            folder_indexes, message_index = _message_locator(
                connection, store_uid, message_nid
            )
        return reader.extract_attachment(
            folder_indexes,
            message_index,
            message_nid,
            attachment_index,
            output_path,
        )


def _message_locator(
    connection: sqlite3.Connection, store_uid: str, message_nid: int
) -> tuple[tuple[int, ...], int]:
    row = connection.execute(
        """
        SELECT folder_nid, index_in_folder
        FROM message WHERE store_uid = ? AND nid = ?
        """,
        (store_uid, message_nid),
    ).fetchone()
    if row is None or not isinstance(row[1], int) or row[1] < 0:
        raise ValueError(
            f"No usable locator for message: {_record_id(store_uid, message_nid)}"
        )

    folder_nid = row[0]
    folder_indexes: list[int] = []
    visited: set[int] = set()
    while True:
        if folder_nid in visited:
            raise ValueError(f"Invalid folder ancestry for message: {message_nid}")
        visited.add(folder_nid)
        folder = connection.execute(
            """
            SELECT parent_nid, index_in_parent
            FROM folder WHERE store_uid = ? AND nid = ?
            """,
            (store_uid, folder_nid),
        ).fetchone()
        if folder is None:
            raise ValueError(f"Invalid folder ancestry for message: {message_nid}")
        parent_nid, index_in_parent = folder
        if parent_nid is None:
            if index_in_parent is not None:
                raise ValueError(f"Invalid folder ancestry for message: {message_nid}")
            break
        if not isinstance(index_in_parent, int) or index_in_parent < 0:
            raise ValueError(f"Invalid folder ancestry for message: {message_nid}")
        folder_indexes.append(index_in_parent)
        folder_nid = parent_nid
    return tuple(reversed(folder_indexes)), row[1]


def _full_sync(
    source_path: str | Path, target: Path, history: HistorySettings
) -> SyncResult:
    result = import_pst(source_path, target, history)
    return SyncResult(
        result.store_uid,
        result.folder_count,
        result.message_count,
        new_count=result.message_count,
        modified_count=0,
        moved_count=0,
        deleted_count=0,
        skipped=False,
        full=True,
    )


def _incremental_sync(
    source_path: str | Path,
    target: Path,
    source: _SourceState,
    state: _IndexState,
    history: HistorySettings,
) -> SyncResult | None:
    temporary_path = _temporary_database_path(target)
    try:
        _copy_database(target, temporary_path)
        with PstReader(source_path) as reader:
            store_uid = reader.store.uid
            folders = tuple(reader.walk())

        # A replacement PST can have the same path but a different native store.
        # Rebuild rather than mixing identities in the existing cache.
        if store_uid != state.store_uid:
            temporary_path.unlink(missing_ok=True)
            return None

        with sqlite3.connect(temporary_path) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            generation = state.generation + 1
            new_count, modified_count, moved_count, body_nids = _apply_metadata_scan(
                connection, store_uid, folders, generation
            )
            _load_changed_bodies(
                connection, source_path, store_uid, body_nids, generation
            )
            _delete_search_documents(
                connection,
                """
                store_uid = ? AND native_nid IN (
                    SELECT nid FROM message
                    WHERE store_uid = ? AND last_seen_generation != ?
                )
                """,
                (store_uid, store_uid, generation),
            )
            deleted_count = connection.execute(
                """
                DELETE FROM message
                WHERE store_uid = ? AND last_seen_generation != ?
                """,
                (store_uid, generation),
            ).rowcount
            connection.execute(
                """
                DELETE FROM folder
                WHERE store_uid = ? AND last_seen_generation != ?
                """,
                (store_uid, generation),
            )
            _rebuild_recovered_messages(connection, store_uid, history)
            _assert_source_unchanged(source)
            _write_index_state(connection, source, store_uid, generation, history)
            folder_count, message_count = _cache_counts(connection, store_uid)

        os.replace(temporary_path, target)
        return SyncResult(
            store_uid,
            folder_count,
            message_count,
            new_count,
            modified_count,
            moved_count,
            deleted_count,
            skipped=False,
            full=False,
        )
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def _apply_metadata_scan(
    connection: sqlite3.Connection,
    store_uid: str,
    folders: tuple[PstFolder, ...],
    generation: int,
) -> tuple[int, int, int, set[int]]:
    new_count = modified_count = moved_count = 0
    body_nids: set[int] = set()
    for folder in folders:
        _upsert_folder(connection, store_uid, folder, generation)
        for message in folder.messages:
            existing = connection.execute(
                """
                SELECT modification_time, folder_nid, index_in_folder
                FROM message WHERE store_uid = ? AND nid = ?
                """,
                (store_uid, message.nid),
            ).fetchone()
            modification_time = _format_time(message.modification_time)
            if existing is None:
                new_count += 1
                body_nids.add(message.nid)
            elif existing[0] != modification_time:
                modified_count += 1
                body_nids.add(message.nid)
            elif (
                existing[1] != message.folder_nid
                or existing[2] != message.index_in_folder
            ):
                moved_count += 1
                connection.execute(
                    """
                    UPDATE message
                    SET folder_nid = ?, index_in_folder = ?, last_seen_generation = ?
                    WHERE store_uid = ? AND nid = ?
                    """,
                    (
                        message.folder_nid,
                        message.index_in_folder,
                        generation,
                        store_uid,
                        message.nid,
                    ),
                )
                _index_message(connection, store_uid, message.nid)
                continue
            else:
                connection.execute(
                    """
                    UPDATE message SET last_seen_generation = ?
                    WHERE store_uid = ? AND nid = ?
                    """,
                    (generation, store_uid, message.nid),
                )
                continue

            # New and modified records are marked once their full body is read.
    return new_count, modified_count, moved_count, body_nids


def _load_changed_bodies(
    connection: sqlite3.Connection,
    source_path: str | Path,
    store_uid: str,
    body_nids: set[int],
    generation: int,
) -> None:
    if not body_nids:
        return
    found: set[int] = set()
    with PstReader(source_path) as reader:
        if reader.store.uid != store_uid:
            raise PstSynchronizationError("PST store changed during synchronization.")
        for folder in reader.walk(include_body_nids=body_nids):
            for message in folder.messages:
                if message.nid in body_nids:
                    _upsert_message(connection, store_uid, message, generation)
                    found.add(message.nid)
    if found != body_nids:
        raise PstSynchronizationError("PST messages changed during synchronization.")


def _write_index(
    source_path: str | Path,
    database_path: Path,
    source: _SourceState,
    history: HistorySettings,
) -> ImportResult:
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        _create_schema(connection)
        with connection, PstReader(source_path) as reader:
            store_uid = reader.store.uid
            connection.execute("INSERT INTO store (uid) VALUES (?)", (store_uid,))
            folder_count = message_count = 0
            for folder in reader.walk(include_bodies=True):
                _upsert_folder(connection, store_uid, folder, generation=1)
                folder_count += 1
                for message in folder.messages:
                    _upsert_message(connection, store_uid, message, generation=1)
                    message_count += 1
            _assert_source_unchanged(source)
            _rebuild_recovered_messages(connection, store_uid, history)
            _write_index_state(
                connection, source, store_uid, generation=1, history=history
            )
    finally:
        connection.close()
    return ImportResult(store_uid, folder_count, message_count)


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE store (
            uid TEXT PRIMARY KEY
        );

        CREATE TABLE index_state (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            source_path TEXT NOT NULL,
            source_size INTEGER NOT NULL,
            source_mtime_ns INTEGER NOT NULL,
            store_uid TEXT NOT NULL REFERENCES store(uid),
            schema_version INTEGER NOT NULL,
            cleaner_version INTEGER NOT NULL,
            history_fingerprint TEXT NOT NULL,
            last_successful_sync TEXT NOT NULL,
            generation INTEGER NOT NULL
        );

        CREATE TABLE folder (
            store_uid TEXT NOT NULL REFERENCES store(uid),
            nid INTEGER NOT NULL,
            parent_nid INTEGER,
            name TEXT,
            path TEXT NOT NULL,
            index_in_parent INTEGER,
            last_seen_generation INTEGER NOT NULL,
            PRIMARY KEY (store_uid, nid)
        );

        CREATE TABLE message (
            store_uid TEXT NOT NULL,
            nid INTEGER NOT NULL,
            folder_nid INTEGER NOT NULL,
            modification_time TEXT,
            subject TEXT,
            sender_name TEXT,
            client_submit_time TEXT,
            delivery_time TEXT,
            transport_headers TEXT,
            internet_message_id TEXT,
            in_reply_to TEXT,
            references_header TEXT,
            conversation_topic TEXT,
            conversation_index TEXT,
            attachment_count INTEGER NOT NULL,
            body_raw TEXT,
            body_clean TEXT,
            body_format TEXT,
            index_in_folder INTEGER NOT NULL,
            last_seen_generation INTEGER NOT NULL,
            PRIMARY KEY (store_uid, nid),
            FOREIGN KEY (store_uid, folder_nid) REFERENCES folder(store_uid, nid)
        );

        CREATE TABLE recipient (
            store_uid TEXT NOT NULL,
            message_nid INTEGER NOT NULL,
            recipient_index INTEGER NOT NULL,
            recipient_type TEXT,
            name TEXT,
            email TEXT,
            PRIMARY KEY (store_uid, message_nid, recipient_index),
            FOREIGN KEY (store_uid, message_nid) REFERENCES message(store_uid, nid)
        );

        CREATE TABLE attachment (
            store_uid TEXT NOT NULL,
            message_nid INTEGER NOT NULL,
            index_in_message INTEGER NOT NULL,
            filename TEXT,
            mime_type TEXT,
            size INTEGER,
            content_id TEXT,
            content_location TEXT,
            attachment_method INTEGER,
            hidden INTEGER,
            rendering_position INTEGER,
            PRIMARY KEY (store_uid, message_nid, index_in_message),
            FOREIGN KEY (store_uid, message_nid) REFERENCES message(store_uid, nid)
        );

        CREATE TABLE recovered_message (
            store_uid TEXT NOT NULL REFERENCES store(uid),
            fingerprint TEXT NOT NULL,
            sender TEXT NOT NULL,
            sender_email TEXT,
            recipients_json TEXT NOT NULL,
            subject TEXT NOT NULL,
            sent_at TEXT,
            sent_raw TEXT NOT NULL,
            body TEXT NOT NULL,
            relation TEXT NOT NULL,
            PRIMARY KEY (store_uid, fingerprint)
        );

        CREATE TABLE quote_occurrence (
            store_uid TEXT NOT NULL,
            source_message_nid INTEGER NOT NULL,
            recovered_fingerprint TEXT NOT NULL,
            quote_index INTEGER NOT NULL,
            PRIMARY KEY (
                store_uid, source_message_nid, recovered_fingerprint, quote_index
            ),
            FOREIGN KEY (store_uid, source_message_nid)
                REFERENCES message(store_uid, nid) ON DELETE CASCADE,
            FOREIGN KEY (store_uid, recovered_fingerprint)
                REFERENCES recovered_message(store_uid, fingerprint) ON DELETE CASCADE
        );

        CREATE TABLE search_document (
            store_uid TEXT NOT NULL REFERENCES store(uid),
            selector TEXT NOT NULL,
            native_nid INTEGER,
            recovered_fingerprint TEXT,
            canonical_source_nid INTEGER NOT NULL,
            folder_nid INTEGER NOT NULL,
            folder_path TEXT NOT NULL,
            date TEXT,
            sender TEXT,
            sender_aliases TEXT NOT NULL,
            recipients_json TEXT NOT NULL,
            recipients_text TEXT NOT NULL,
            subject TEXT,
            has_attachment INTEGER NOT NULL,
            body TEXT,
            PRIMARY KEY (store_uid, selector),
            CHECK (
                (native_nid IS NOT NULL AND recovered_fingerprint IS NULL)
                OR (native_nid IS NULL AND recovered_fingerprint IS NOT NULL)
            )
        );

        CREATE VIRTUAL TABLE search_fts USING fts5(
            subject,
            sender,
            recipients,
            body
        );
        """
    )


def _upsert_folder(
    connection: sqlite3.Connection,
    store_uid: str,
    folder: PstFolder,
    generation: int,
) -> None:
    connection.execute(
        """
        INSERT INTO folder (
            store_uid, nid, parent_nid, name, path, index_in_parent,
            last_seen_generation
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(store_uid, nid) DO UPDATE SET
            parent_nid = excluded.parent_nid,
            name = excluded.name,
            path = excluded.path,
            index_in_parent = excluded.index_in_parent,
            last_seen_generation = excluded.last_seen_generation
        """,
        (
            store_uid,
            folder.nid,
            folder.parent_nid,
            folder.name,
            folder.path,
            folder.index_in_parent,
            generation,
        ),
    )


def _upsert_message(
    connection: sqlite3.Connection,
    store_uid: str,
    message: PstMessage,
    generation: int,
) -> None:
    body_raw, body_format = _select_body(message)
    relationships = _relationships(message.transport_headers)
    connection.execute(
        """
        INSERT INTO message (
            store_uid, nid, folder_nid, modification_time, subject, sender_name,
            client_submit_time, delivery_time, transport_headers, internet_message_id,
            in_reply_to, references_header, conversation_topic, conversation_index,
            attachment_count, body_raw, body_clean, body_format, index_in_folder,
            last_seen_generation
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(store_uid, nid) DO UPDATE SET
            folder_nid = excluded.folder_nid,
            modification_time = excluded.modification_time,
            subject = excluded.subject,
            sender_name = excluded.sender_name,
            client_submit_time = excluded.client_submit_time,
            delivery_time = excluded.delivery_time,
            transport_headers = excluded.transport_headers,
            internet_message_id = excluded.internet_message_id,
            in_reply_to = excluded.in_reply_to,
            references_header = excluded.references_header,
            conversation_topic = excluded.conversation_topic,
            conversation_index = excluded.conversation_index,
            attachment_count = excluded.attachment_count,
            body_raw = excluded.body_raw,
            body_clean = excluded.body_clean,
            body_format = excluded.body_format,
            index_in_folder = excluded.index_in_folder,
            last_seen_generation = excluded.last_seen_generation
        """,
        (
            store_uid,
            message.nid,
            message.folder_nid,
            _format_time(message.modification_time),
            message.subject,
            message.sender_name,
            _format_time(message.client_submit_time),
            _format_time(message.delivery_time),
            message.transport_headers,
            message.internet_message_id or relationships["internet_message_id"],
            message.in_reply_to or relationships["in_reply_to"],
            message.references_header or relationships["references_header"],
            message.conversation_topic or relationships["conversation_topic"],
            message.conversation_index or relationships["conversation_index"],
            message.attachment_count,
            body_raw,
            clean_body(
                _render_body(
                    body_raw,
                    body_format,
                    {
                        _normalize_content_id(attachment.content_id): _attachment_id(
                            store_uid, message.nid, attachment.index
                        )
                        for attachment in message.attachments
                        if attachment.content_id
                    },
                )
            ),
            body_format,
            message.index_in_folder,
            generation,
        ),
    )
    _replace_recipients(connection, store_uid, message.nid, message.transport_headers)
    _replace_attachments(connection, store_uid, message.nid, message.attachments)
    _index_message(connection, store_uid, message.nid)


def _source_state(source_path: str | Path) -> _SourceState:
    path = Path(source_path).resolve()
    stat = path.stat()
    return _SourceState(str(path), stat.st_size, stat.st_mtime_ns)


def _assert_source_unchanged(source: _SourceState) -> None:
    if _source_state(source.path) != source:
        raise PstSynchronizationError("PST changed during synchronization.")


def _temporary_database_path(target: Path) -> Path:
    with NamedTemporaryFile(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False
    ) as temporary_file:
        return Path(temporary_file.name)


def _copy_database(source: Path, target: Path) -> None:
    with sqlite3.connect(source) as source_connection:
        with sqlite3.connect(target) as target_connection:
            source_connection.backup(target_connection)


def _read_index_state(database_path: Path) -> _IndexState | None:
    state, _ = _read_status_state(database_path)
    return state


def _read_status_state(database_path: Path) -> tuple[_IndexState | None, str | None]:
    try:
        with sqlite3.connect(database_path) as connection:
            row = connection.execute(
                """
                SELECT source_path, source_size, source_mtime_ns, store_uid,
                       schema_version, cleaner_version, history_fingerprint, generation,
                       last_successful_sync
                FROM index_state WHERE singleton = 1
                """
            ).fetchone()
    except sqlite3.Error:
        return None, None
    if row is None:
        return None, None
    return (
        _IndexState(
            _SourceState(row[0], row[1], row[2]), row[3], row[4], row[5], row[7], row[6]
        ),
        row[8],
    )


def _write_index_state(
    connection: sqlite3.Connection,
    source: _SourceState,
    store_uid: str,
    generation: int,
    history: HistorySettings,
) -> None:
    connection.execute(
        """
        INSERT INTO index_state (
            singleton, source_path, source_size, source_mtime_ns, store_uid,
            schema_version, cleaner_version, history_fingerprint, last_successful_sync,
            generation
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(singleton) DO UPDATE SET
            source_path = excluded.source_path,
            source_size = excluded.source_size,
            source_mtime_ns = excluded.source_mtime_ns,
            store_uid = excluded.store_uid,
            schema_version = excluded.schema_version,
            cleaner_version = excluded.cleaner_version,
            history_fingerprint = excluded.history_fingerprint,
            last_successful_sync = excluded.last_successful_sync,
            generation = excluded.generation
        """,
        (
            source.path,
            source.size,
            source.mtime_ns,
            store_uid,
            SCHEMA_VERSION,
            CLEANER_VERSION,
            _history_fingerprint(history),
            datetime.now(UTC).isoformat(),
            generation,
        ),
    )


def _cache_counts(
    connection_or_path: sqlite3.Connection | Path, store_uid: str
) -> tuple[int, int]:
    if isinstance(connection_or_path, Path):
        with sqlite3.connect(connection_or_path) as connection:
            return _cache_counts(connection, store_uid)
    connection = connection_or_path
    folder_count = connection.execute(
        "SELECT COUNT(*) FROM folder WHERE store_uid = ?", (store_uid,)
    ).fetchone()[0]
    message_count = connection.execute(
        "SELECT COUNT(*) FROM message WHERE store_uid = ?", (store_uid,)
    ).fetchone()[0]
    return folder_count, message_count


def _select_body(message: PstMessage) -> tuple[str | bytes | None, str | None]:
    for body, body_format in (
        (message.plain_text_body, "plain"),
        (message.html_body, "html"),
        (message.rtf_body, "rtf"),
    ):
        if body is not None:
            return body, body_format
    return None, None


def clean_body(body: str | bytes | None) -> str | None:
    """Remove only unambiguous Outlook quoted history from a message body."""
    if body is None:
        return None
    if isinstance(body, bytes):
        body = _decode_sqlite_text(body)
    analysis = analyze_body(body, "UTC")
    if analysis.quoted_messages:
        return analysis.authored_body
    lines = body.splitlines(keepends=True)
    for index, line in enumerate(lines):
        is_separator = _ORIGINAL_MESSAGE_SEPARATOR.fullmatch(line.strip())
        if is_separator:
            return "".join(lines[:index])
    return body


def _render_body(
    body: str | bytes | None, body_format: str | None, attachment_ids: dict[str, str]
) -> str | bytes | None:
    if body is None or body_format != "html":
        return body
    if isinstance(body, bytes):
        body = _decode_sqlite_text(body)
    renderer = _HtmlBodyRenderer(attachment_ids)
    renderer.feed(body)
    renderer.close()
    return renderer.rendered()


def _image_marker(source: str | None, attachment_ids: dict[str, str]) -> str:
    if not source:
        return "[image: missing source]"
    source = source.strip()
    if source.casefold().startswith("cid:"):
        content_id = _normalize_content_id(source[4:])
        attachment_id = attachment_ids.get(content_id)
        return (
            f"[attachment: {attachment_id}]"
            if attachment_id
            else f"[image: unresolved cid:{_bounded(source[4:])}]"
        )
    if source.casefold().startswith("data:"):
        return "[image: embedded data]"
    return f"[image: remote {_bounded(source)}]"


def _normalize_content_id(value: str) -> str:
    return value.strip().strip("<>").casefold()


def _bounded(value: str, limit: int = 120) -> str:
    return value if len(value) <= limit else f"{value[:limit]}..."


def _relationships(headers: str | None) -> dict[str, str | None]:
    if headers is None:
        return {
            "internet_message_id": None,
            "in_reply_to": None,
            "references_header": None,
            "conversation_topic": None,
            "conversation_index": None,
        }
    parsed = HeaderParser(policy=policy.default).parsestr(headers)
    return {
        "internet_message_id": parsed.get("Message-ID"),
        "in_reply_to": parsed.get("In-Reply-To"),
        "references_header": parsed.get("References"),
        "conversation_topic": parsed.get("Thread-Topic"),
        "conversation_index": _thread_index(parsed.get("Thread-Index")),
    }


def _thread_index(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        decoded = b64decode(value, validate=True)
    except (BinasciiError, ValueError):
        return None
    return decoded.hex() if decoded else None


def _thread_members(
    rows: Sequence[Sequence[object]], anchor_nid: int
) -> tuple[int, ...]:
    """Choose the strongest available indexed relationship component."""
    metadata = {cast(int, row[0]): row for row in rows}
    message_ids: dict[str, set[int]] = {}
    for nid, row in metadata.items():
        for value in _message_ids(_sqlite_optional_text(row[1])):
            message_ids.setdefault(value, set()).add(nid)

    neighbors: dict[int, set[int]] = {nid: set() for nid in metadata}
    for matching_nids in message_ids.values():
        for nid in matching_nids:
            neighbors[nid].update(matching_nids - {nid})
    for nid, row in metadata.items():
        references = _message_ids(_sqlite_optional_text(row[2]))
        references.update(_message_ids(_sqlite_optional_text(row[3])))
        for reference in references:
            for target_nid in message_ids.get(reference, ()):
                if target_nid != nid:
                    neighbors[nid].add(target_nid)
                    neighbors[target_nid].add(nid)

    members = _connected_members(neighbors, anchor_nid)
    if len(members) > 1:
        return tuple(members)

    conversation_root = _conversation_root(
        _sqlite_optional_text(metadata[anchor_nid][5])
    )
    if conversation_root is not None:
        members = {
            nid
            for nid, row in metadata.items()
            if _conversation_root(_sqlite_optional_text(row[5])) == conversation_root
        }
        if len(members) > 1:
            return tuple(members)

    topic = _conversation_topic(_sqlite_optional_text(metadata[anchor_nid][4]))
    if topic is not None:
        members = {
            nid
            for nid, row in metadata.items()
            if _conversation_topic(_sqlite_optional_text(row[4])) == topic
        }
        if len(members) > 1:
            return tuple(members)
    return (anchor_nid,)


def _message_ids(value: str | None) -> set[str]:
    return {match.group().casefold() for match in _MESSAGE_ID.finditer(value or "")}


def _connected_members(neighbors: dict[int, set[int]], anchor_nid: int) -> set[int]:
    members = {anchor_nid}
    pending = [anchor_nid]
    while pending:
        nid = pending.pop()
        for neighbor in neighbors[nid] - members:
            members.add(neighbor)
            pending.append(neighbor)
    return members


def _conversation_root(value: str | None) -> str | None:
    if value is None or len(value) < 44 or len(value) % 2:
        return None
    try:
        bytes.fromhex(value)
    except ValueError:
        return None
    return value[:44].casefold()


def _conversation_topic(value: str | None) -> str | None:
    normalized = (value or "").strip().casefold()
    return normalized or None


def _thread_order(row: Sequence[object]) -> tuple[int, datetime, int]:
    value = _sqlite_optional_text(row[6] or row[5])
    if value is not None:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            pass
        else:
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(UTC).replace(tzinfo=None)
            return (0, parsed, cast(int, row[0]))
    return (1, datetime.max, cast(int, row[0]))


def _recovered_message_record(
    store_uid: str, fingerprint: str, row: Sequence[object]
) -> dict[str, object]:
    """Render a recovered record through the ordinary persisted-message schema."""
    return {
        "attachment_count": 0,
        "body": _sqlite_optional_text(row[4]),
        "body_format": "plain",
        "client_submit_time": _sqlite_optional_text(row[3]),
        "conversation_index": None,
        "conversation_topic": None,
        "date": _sqlite_optional_text(row[3]),
        "delivery_time": None,
        "folder": _sqlite_optional_text(row[6]),
        "folder_id": _record_id(store_uid, cast(int, row[5])),
        "from": _sqlite_optional_text(row[0]),
        "id": _recovered_record_id(store_uid, fingerprint),
        "in_reply_to": None,
        "internet_message_id": None,
        "modification_time": None,
        "references": None,
        "subject": _sqlite_optional_text(row[2]),
        "to": json.loads(_sqlite_optional_text(row[1]) or "[]"),
        "transport_headers": None,
    }


def _recovered_message_records(
    store_uid: str, rows: Sequence[Sequence[object]]
) -> list[dict[str, object]]:
    return [
        _recovered_message_record(store_uid, cast(str, row[0]), row[1:]) for row in rows
    ]


def _record_order(record: dict[str, object]) -> tuple[int, datetime, str]:
    value = cast(str | None, record["date"])
    if value is not None:
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            pass
        else:
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(UTC).replace(tzinfo=None)
            return (0, parsed, cast(str, record["id"]))
    return (1, datetime.max, cast(str, record["id"]))


def _replace_recipients(
    connection: sqlite3.Connection,
    store_uid: str,
    message_nid: int,
    headers: str | None,
) -> None:
    connection.execute(
        "DELETE FROM recipient WHERE store_uid = ? AND message_nid = ?",
        (store_uid, message_nid),
    )
    if headers is None:
        return
    parsed = HeaderParser(policy=policy.default).parsestr(headers)
    rows: list[tuple[str, str | None, str | None]] = []
    for recipient_type, header_name in (("to", "To"), ("cc", "Cc"), ("bcc", "Bcc")):
        for name, email in getaddresses(parsed.get_all(header_name, ())):
            rows.append((recipient_type, name or None, email or None))
    connection.executemany(
        """
        INSERT INTO recipient (
            store_uid, message_nid, recipient_index, recipient_type, name, email
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (store_uid, message_nid, index, recipient_type, name, email)
            for index, (recipient_type, name, email) in enumerate(rows)
        ],
    )


def _replace_attachments(
    connection: sqlite3.Connection,
    store_uid: str,
    message_nid: int,
    attachments: tuple[PstAttachment, ...],
) -> None:
    connection.execute(
        "DELETE FROM attachment WHERE store_uid = ? AND message_nid = ?",
        (store_uid, message_nid),
    )
    connection.executemany(
        """
        INSERT INTO attachment (
            store_uid, message_nid, index_in_message, filename, mime_type, size,
            content_id, content_location, attachment_method, hidden, rendering_position
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                store_uid,
                message_nid,
                attachment.index,
                attachment.filename,
                attachment.mime_type,
                attachment.size,
                attachment.content_id,
                attachment.content_location,
                attachment.attachment_method,
                attachment.hidden,
                attachment.rendering_position,
            )
            for attachment in attachments
        ],
    )


def _index_message(connection: sqlite3.Connection, store_uid: str, nid: int) -> None:
    row = connection.execute(
        """
        SELECT message.subject, message.sender_name,
               COALESCE(message.delivery_time, message.client_submit_time),
               message.attachment_count, message.body_clean, message.transport_headers,
               folder.nid, folder.path,
               group_concat(
                   TRIM(
                       COALESCE(recipient.name || ' ', '')
                       || COALESCE(recipient.email, '')
                   ),
                   ' '
               )
        FROM message
        LEFT JOIN recipient ON recipient.store_uid = message.store_uid
                           AND recipient.message_nid = message.nid
        JOIN folder ON folder.store_uid = message.store_uid
                   AND folder.nid = message.folder_nid
        WHERE message.store_uid = ? AND message.nid = ?
        GROUP BY message.store_uid, message.nid
        """,
        (store_uid, nid),
    ).fetchone()
    if row is None:
        return
    recipients = _recipients_for_messages(connection, store_uid, ((nid,),))[nid]
    sender = _sqlite_optional_text(row[1])
    sender_email = _header_sender_email(_sqlite_optional_text(row[5]))
    _upsert_search_document(
        connection,
        store_uid,
        _record_id(store_uid, nid),
        native_nid=nid,
        recovered_fingerprint=None,
        canonical_source_nid=nid,
        folder_nid=cast(int, row[6]),
        folder_path=cast(str, row[7]),
        date=_sqlite_optional_text(row[2]),
        sender=sender,
        sender_aliases=" ".join(value for value in (sender, sender_email) if value),
        recipients=recipients,
        subject=_sqlite_optional_text(row[0]),
        has_attachment=bool(row[3]),
        body=_sqlite_optional_text(row[4]),
    )


def _upsert_search_document(
    connection: sqlite3.Connection,
    store_uid: str,
    selector: str,
    *,
    native_nid: int | None,
    recovered_fingerprint: str | None,
    canonical_source_nid: int,
    folder_nid: int,
    folder_path: str,
    date: str | None,
    sender: str | None,
    sender_aliases: str,
    recipients: Sequence[str],
    subject: str | None,
    has_attachment: bool,
    body: str | None,
) -> None:
    """Replace one normalized search document and its corresponding FTS row."""
    existing = connection.execute(
        "SELECT rowid FROM search_document WHERE store_uid = ? AND selector = ?",
        (store_uid, selector),
    ).fetchone()
    if existing is not None:
        connection.execute("DELETE FROM search_fts WHERE rowid = ?", (existing[0],))
    recipients_json = json.dumps(recipients)
    recipients_text = " ".join(recipients)
    connection.execute(
        """
        INSERT INTO search_document (
            store_uid, selector, native_nid, recovered_fingerprint,
            canonical_source_nid, folder_nid, folder_path, date, sender,
            sender_aliases, recipients_json, recipients_text, subject,
            has_attachment, body
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(store_uid, selector) DO UPDATE SET
            native_nid = excluded.native_nid,
            recovered_fingerprint = excluded.recovered_fingerprint,
            canonical_source_nid = excluded.canonical_source_nid,
            folder_nid = excluded.folder_nid,
            folder_path = excluded.folder_path,
            date = excluded.date,
            sender = excluded.sender,
            sender_aliases = excluded.sender_aliases,
            recipients_json = excluded.recipients_json,
            recipients_text = excluded.recipients_text,
            subject = excluded.subject,
            has_attachment = excluded.has_attachment,
            body = excluded.body
        """,
        (
            store_uid,
            selector,
            native_nid,
            recovered_fingerprint,
            canonical_source_nid,
            folder_nid,
            folder_path,
            date,
            sender,
            sender_aliases,
            recipients_json,
            recipients_text,
            subject,
            has_attachment,
            body,
        ),
    )
    rowid = connection.execute(
        "SELECT rowid FROM search_document WHERE store_uid = ? AND selector = ?",
        (store_uid, selector),
    ).fetchone()[0]
    connection.execute(
        """
        INSERT INTO search_fts (rowid, subject, sender, recipients, body)
        VALUES (?, ?, ?, ?, ?)
        """,
        (rowid, subject, sender, recipients_text, body),
    )


def _delete_search_documents(
    connection: sqlite3.Connection, where: str, parameters: Sequence[object]
) -> None:
    """Remove projection and FTS rows selected by an internal SQL predicate."""
    connection.execute(
        "DELETE FROM search_fts WHERE rowid IN "
        f"(SELECT rowid FROM search_document WHERE {where})",
        parameters,
    )
    connection.execute(f"DELETE FROM search_document WHERE {where}", parameters)


def _rebuild_recovered_messages(
    connection: sqlite3.Connection, store_uid: str, history: HistorySettings
) -> None:
    """Recreate derived quote records from native bodies in this transaction."""
    _delete_search_documents(
        connection,
        "store_uid = ? AND recovered_fingerprint IS NOT NULL",
        (store_uid,),
    )
    connection.execute("DELETE FROM quote_occurrence WHERE store_uid = ?", (store_uid,))
    connection.execute(
        "DELETE FROM recovered_message WHERE store_uid = ?", (store_uid,)
    )
    if not history.enabled:
        return
    owner_emails = frozenset(value.strip().casefold() for value in history.owner_emails)
    owner_names = frozenset(_normalized_name(value) for value in history.owner_names)
    native_rows = connection.execute(
        """
        SELECT nid, sender_name, subject, client_submit_time, delivery_time,
               transport_headers, body_raw, body_clean, body_format
        FROM message WHERE store_uid = ?
        """,
        (store_uid,),
    ).fetchall()
    native_fingerprints = {
        native_fingerprint(
            row[1], _header_sender_email(_sqlite_optional_text(row[5])), row[2], row[7]
        )
        for row in native_rows
    }
    recovered: dict[str, QuotedMessage] = {}
    occurrences: list[tuple[str, int, str, int]] = []
    for row in native_rows:
        rendered = _render_body(row[6], _sqlite_optional_text(row[8]), {})
        analysis = analyze_body(rendered, history.timezone)
        for quote in analysis.quoted_messages:
            if (
                not quote.body
                or not is_owner(quote, owner_emails, owner_names)
                or quote.fingerprint in native_fingerprints
            ):
                continue
            recovered.setdefault(quote.fingerprint, quote)
            occurrences.append((store_uid, row[0], quote.fingerprint, quote.index))
    connection.executemany(
        """
        INSERT INTO recovered_message (
            store_uid, fingerprint, sender, sender_email, recipients_json, subject,
            sent_at, sent_raw, body, relation
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                store_uid,
                fingerprint,
                quote.sender,
                quote.sender_email,
                json.dumps(quote.recipients),
                quote.subject,
                quote.sent_at,
                quote.sent_raw,
                quote.body,
                quote.relation,
            )
            for fingerprint, quote in recovered.items()
        ],
    )
    connection.executemany(
        """
        INSERT INTO quote_occurrence (
            store_uid, source_message_nid, recovered_fingerprint, quote_index
        ) VALUES (?, ?, ?, ?)
        """,
        occurrences,
    )
    _index_recovered_messages(connection, store_uid)


def _index_recovered_messages(connection: sqlite3.Connection, store_uid: str) -> None:
    """Materialize each recovered record using its canonical quote occurrence."""
    rows = connection.execute(
        """
        SELECT recovered_message.fingerprint, recovered_message.sender,
               recovered_message.sender_email, recovered_message.recipients_json,
               recovered_message.subject, recovered_message.sent_at,
               recovered_message.body, quote_occurrence.source_message_nid,
               quote_occurrence.quote_index, folder.nid, folder.path
        FROM recovered_message
        JOIN quote_occurrence
          ON quote_occurrence.store_uid = recovered_message.store_uid
         AND quote_occurrence.recovered_fingerprint = recovered_message.fingerprint
        JOIN message ON message.store_uid = quote_occurrence.store_uid
                    AND message.nid = quote_occurrence.source_message_nid
        JOIN folder ON folder.store_uid = message.store_uid
                   AND folder.nid = message.folder_nid
        WHERE recovered_message.store_uid = ?
        ORDER BY recovered_message.fingerprint, quote_occurrence.source_message_nid,
                 quote_occurrence.quote_index
        """,
        (store_uid,),
    ).fetchall()
    fingerprints: set[str] = set()
    for row in rows:
        fingerprint = cast(str, row[0])
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        sender = _sqlite_optional_text(row[1])
        sender_email = _sqlite_optional_text(row[2])
        _upsert_search_document(
            connection,
            store_uid,
            _recovered_record_id(store_uid, fingerprint),
            native_nid=None,
            recovered_fingerprint=fingerprint,
            canonical_source_nid=cast(int, row[7]),
            folder_nid=cast(int, row[9]),
            folder_path=cast(str, row[10]),
            date=_sqlite_optional_text(row[5]),
            sender=sender,
            sender_aliases=" ".join(value for value in (sender, sender_email) if value),
            recipients=tuple(json.loads(_sqlite_optional_text(row[3]) or "[]")),
            subject=_sqlite_optional_text(row[4]),
            has_attachment=False,
            body=_sqlite_optional_text(row[6]),
        )


def _header_sender_email(headers: str | None) -> str | None:
    if headers is None:
        return None
    parsed = HeaderParser(policy=policy.default).parsestr(headers)
    addresses = getaddresses(parsed.get_all("From", ()))
    return addresses[0][1].casefold() if addresses and addresses[0][1] else None


def _history_fingerprint(history: HistorySettings) -> str:
    values = "\n".join(
        (
            str(ANALYZER_VERSION),
            history.timezone,
            *sorted(value.strip().casefold() for value in history.owner_emails),
            *sorted(_normalized_name(value) for value in history.owner_names),
        )
    )
    return sha256(values.encode()).hexdigest()


def _normalized_name(value: str) -> str:
    return " ".join(value.split()).casefold()


def _recipients_for_messages(
    connection: sqlite3.Connection,
    store_uid: str,
    messages: Sequence[tuple[object, ...]],
) -> dict[int, tuple[str, ...]]:
    nids = [cast(int, row[0]) for row in messages]
    if not nids:
        return {}
    placeholders = ", ".join("?" for _ in nids)
    rows = connection.execute(
        f"""
        SELECT message_nid, name, email
        FROM recipient
        WHERE store_uid = ? AND message_nid IN ({placeholders})
        ORDER BY message_nid, recipient_index
        """,
        (store_uid, *nids),
    ).fetchall()
    recipients: dict[int, list[str]] = {nid: [] for nid in nids}
    for message_nid, name, email in rows:
        recipients[message_nid].append(_sqlite_optional_text(email or name) or "")
    return {nid: tuple(values) for nid, values in recipients.items()}


def _require_index_state(database_path: str | Path) -> _IndexState:
    state = _read_index_state(Path(database_path))
    if (
        state is None
        or state.schema_version != SCHEMA_VERSION
        or state.cleaner_version != CLEANER_VERSION
    ):
        raise ValueError("No current SQLite index is available.")
    return state


def _record_id(store_uid: str, nid: int) -> str:
    return f"{store_uid}:{nid}"


def _recovered_record_id(store_uid: str, fingerprint: str) -> str:
    return f"{store_uid}:q:{fingerprint}"


def _parse_recovered_record_id(value: str) -> tuple[str, str] | None:
    store_uid, separator, fingerprint = value.partition(":q:")
    return (store_uid, fingerprint) if separator and store_uid and fingerprint else None


def _attachment_id(store_uid: str, message_nid: int, attachment_index: int) -> str:
    return f"{store_uid}:{message_nid}:{attachment_index}"


def _parse_record_id(value: str) -> tuple[str, int]:
    store_uid, separator, nid_text = value.rpartition(":")
    if not separator or not store_uid:
        raise ValueError(f"Invalid message ID: {value}")
    try:
        return store_uid, int(nid_text)
    except ValueError as error:
        raise ValueError(f"Invalid message ID: {value}") from error


def _parse_attachment_id(value: str) -> tuple[str, int, int]:
    message_id, separator, attachment_index_text = value.rpartition(":")
    if not separator:
        raise ValueError(f"Invalid attachment ID: {value}")
    try:
        store_uid, message_nid = _parse_record_id(message_id)
    except ValueError as error:
        raise ValueError(f"Invalid attachment ID: {value}") from error
    try:
        attachment_index = int(attachment_index_text)
    except ValueError as error:
        raise ValueError(f"Invalid attachment ID: {value}") from error
    if attachment_index < 0:
        raise ValueError(f"Invalid attachment ID: {value}")
    return store_uid, message_nid, attachment_index


def _decode_sqlite_text(value: bytes) -> str:
    """Preserve readable FTS output when a PST body contains invalid UTF-8."""
    return value.decode("utf-8", errors="replace")


def _sqlite_optional_text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return _decode_sqlite_text(value)
    return cast(str, value)


def _format_time(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
