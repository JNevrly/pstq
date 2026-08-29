"""Disposable SQLite cache creation and atomic incremental synchronization."""

from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from email import policy
from email.parser import HeaderParser
from email.utils import getaddresses
from html.parser import HTMLParser
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast

from pstq.pst import PstAttachment, PstFolder, PstMessage, PstReader

SCHEMA_VERSION = 5
CLEANER_VERSION = 2

_ORIGINAL_MESSAGE_SEPARATOR = re.compile(
    r"^-----Original Message-----\s*$", re.IGNORECASE
)
_OUTLOOK_HEADER = re.compile(r"^(From|Sent|To|Cc|Subject):\s+\S.*", re.IGNORECASE)
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


def import_pst(source_path: str | Path, database_path: str | Path) -> ImportResult:
    """Build DATABASE_PATH from SOURCE_PATH without risking its current contents."""
    source = _source_state(source_path)
    target = Path(database_path)
    temporary_path = _temporary_database_path(target)
    try:
        result = _write_index(source_path, temporary_path, source)
        os.replace(temporary_path, target)
        return result
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def sync_pst(
    source_path: str | Path, database_path: str | Path, *, full: bool = False
) -> SyncResult:
    """Synchronize DATABASE_PATH with SOURCE_PATH without replacing a usable cache.

    The normal path scans only metadata, then reads bodies solely for new or
    modified messages.  All changes are made to a temporary database and
    atomically swapped into place only after the source is verified unchanged.
    """
    target = Path(database_path)
    if full or not target.is_file():
        return _full_sync(source_path, target)

    state = _read_index_state(target)
    if (
        state is None
        or state.schema_version != SCHEMA_VERSION
        or state.cleaner_version != CLEANER_VERSION
    ):
        return _full_sync(source_path, target)

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

    result = _incremental_sync(source_path, target, source, state)
    return result if result is not None else _full_sync(source_path, target)


def index_status(
    source_path: str | Path, database_path: str | Path
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
    recipient: str | None = None,
    after: str | None = None,
    before: str | None = None,
    folder: str | None = None,
    has_attachment: bool = False,
    limit: int = 20,
) -> list[SearchResult]:
    """Search indexed messages with FTS5 and structured SQL filters."""
    if not query.strip():
        raise ValueError("Search query must not be empty.")
    state = _require_index_state(database_path)
    filters = ["message_fts MATCH ?", "message.store_uid = ?"]
    parameters: list[object] = [query, state.store_uid]
    if sender:
        filters.append("message.sender_name LIKE ? COLLATE NOCASE")
        parameters.append(f"%{sender}%")
    if recipient:
        filters.append(
            """
            EXISTS (
                SELECT 1 FROM recipient
                WHERE recipient.store_uid = message.store_uid
                  AND recipient.message_nid = message.nid
                  AND (recipient.name LIKE ? COLLATE NOCASE
                       OR recipient.email LIKE ? COLLATE NOCASE)
            )
            """
        )
        parameters.extend((f"%{recipient}%", f"%{recipient}%"))
    if after:
        filters.append(
            "COALESCE(message.delivery_time, message.client_submit_time) >= ?"
        )
        parameters.append(after)
    if before:
        filters.append(
            "COALESCE(message.delivery_time, message.client_submit_time) < ?"
        )
        parameters.append(before)
    if folder:
        filters.append("folder.path = ?")
        parameters.append(folder)
    if has_attachment:
        filters.append("message.attachment_count > 0")

    statement = f"""
        SELECT message.nid, message.subject, message.sender_name,
               COALESCE(message.delivery_time, message.client_submit_time),
               folder.path,
               snippet(message_fts, -1, '', '', '...', 20),
               -bm25(message_fts)
        FROM message_fts
        JOIN message ON message.rowid = message_fts.rowid
        JOIN folder ON folder.store_uid = message.store_uid
                   AND folder.nid = message.folder_nid
        WHERE {" AND ".join(filters)}
        ORDER BY bm25(message_fts), message.nid
        LIMIT ?
    """
    parameters.append(limit)
    try:
        with sqlite3.connect(database_path) as connection:
            connection.text_factory = _decode_sqlite_text
            rows = connection.execute(statement, parameters).fetchall()
            recipients = _recipients_for_messages(connection, state.store_uid, rows)
    except sqlite3.OperationalError as error:
        if any(
            value in str(error).lower()
            for value in ("fts5", "syntax error", "unterminated string")
        ):
            raise ValueError(f"Invalid FTS query: {query}") from error
        raise
    return [
        SearchResult(
            id=_record_id(state.store_uid, row[0]),
            subject=row[1],
            sender=row[2],
            date=row[3],
            folder=row[4],
            snippet=row[5] or "",
            score=row[6],
            recipients=recipients.get(row[0], ()),
        )
        for row in rows
    ]


def get_message(
    database_path: str | Path, message_id: str, *, full: bool = False
) -> dict[str, object]:
    """Return a persisted message with its cleaned body unless FULL is requested."""
    store_uid, nid = _parse_record_id(message_id)
    state = _require_index_state(database_path)
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
        "folder_id": _record_id(store_uid, row[1]),
        "from": _sqlite_optional_text(row[4]),
        "id": message_id,
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
    store_uid, message_nid = _parse_record_id(message_id)
    state = _require_index_state(database_path)
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
) -> int:
    """Extract one persisted attachment through a cached traversal locator."""
    store_uid, message_nid, attachment_index = _parse_attachment_id(attachment_id)
    sync_pst(source_path, database_path)
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


def _full_sync(source_path: str | Path, target: Path) -> SyncResult:
    result = import_pst(source_path, target)
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
            connection.execute(
                """
                DELETE FROM message_fts
                WHERE rowid IN (
                    SELECT rowid FROM message
                    WHERE store_uid = ? AND last_seen_generation != ?
                )
                """,
                (store_uid, generation),
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
            _assert_source_unchanged(source)
            _write_index_state(connection, source, store_uid, generation)
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
    source_path: str | Path, database_path: Path, source: _SourceState
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
            _write_index_state(connection, source, store_uid, generation=1)
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

        CREATE VIRTUAL TABLE message_fts USING fts5(
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
            relationships["internet_message_id"],
            relationships["in_reply_to"],
            relationships["references_header"],
            message.conversation_topic,
            message.conversation_index,
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
                       schema_version, cleaner_version, generation, last_successful_sync
                FROM index_state WHERE singleton = 1
                """
            ).fetchone()
    except sqlite3.Error:
        return None, None
    if row is None:
        return None, None
    return (
        _IndexState(
            _SourceState(row[0], row[1], row[2]), row[3], row[4], row[5], row[6]
        ),
        row[7],
    )


def _write_index_state(
    connection: sqlite3.Connection,
    source: _SourceState,
    store_uid: str,
    generation: int,
) -> None:
    connection.execute(
        """
        INSERT INTO index_state (
            singleton, source_path, source_size, source_mtime_ns, store_uid,
            schema_version, cleaner_version, last_successful_sync, generation
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(singleton) DO UPDATE SET
            source_path = excluded.source_path,
            source_size = excluded.source_size,
            source_mtime_ns = excluded.source_mtime_ns,
            store_uid = excluded.store_uid,
            schema_version = excluded.schema_version,
            cleaner_version = excluded.cleaner_version,
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
    lines = body.splitlines(keepends=True)
    for index, line in enumerate(lines):
        is_separator = _ORIGINAL_MESSAGE_SEPARATOR.fullmatch(line.strip())
        if is_separator or _is_outlook_header_block(lines, index):
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


def _is_outlook_header_block(lines: list[str], start: int) -> bool:
    """Recognize the ordered, populated English Outlook reply header block."""
    expected = iter(("from", "sent", "to"))
    for label in expected:
        if start >= len(lines):
            return False
        match = _OUTLOOK_HEADER.fullmatch(lines[start].strip())
        if match is None or match[1].casefold() != label:
            return False
        start += 1
    if start < len(lines):
        match = _OUTLOOK_HEADER.fullmatch(lines[start].strip())
        if match is not None and match[1].casefold() == "cc":
            start += 1
    if start >= len(lines):
        return False
    match = _OUTLOOK_HEADER.fullmatch(lines[start].strip())
    return match is not None and match[1].casefold() == "subject"


def _relationships(headers: str | None) -> dict[str, str | None]:
    if headers is None:
        return {
            "internet_message_id": None,
            "in_reply_to": None,
            "references_header": None,
        }
    parsed = HeaderParser(policy=policy.default).parsestr(headers)
    return {
        "internet_message_id": parsed.get("Message-ID"),
        "in_reply_to": parsed.get("In-Reply-To"),
        "references_header": parsed.get("References"),
    }


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
        SELECT message.rowid, message.subject, message.sender_name, message.body_clean,
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
        WHERE message.store_uid = ? AND message.nid = ?
        GROUP BY message.rowid
        """,
        (store_uid, nid),
    ).fetchone()
    if row is None:
        return
    connection.execute("DELETE FROM message_fts WHERE rowid = ?", (row[0],))
    connection.execute(
        """
        INSERT INTO message_fts (rowid, subject, sender, recipients, body)
        VALUES (?, ?, ?, ?, ?)
        """,
        row,
    )


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
