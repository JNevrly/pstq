"""Disposable SQLite cache creation and atomic incremental synchronization."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from email import policy
from email.parser import HeaderParser
from pathlib import Path
from tempfile import NamedTemporaryFile

from pstq.pst import PstFolder, PstMessage, PstReader

SCHEMA_VERSION = 1


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
class _SourceState:
    path: str
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class _IndexState:
    source: _SourceState
    store_uid: str
    schema_version: int
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
    if state is None or state.schema_version != SCHEMA_VERSION:
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
                SELECT modification_time, folder_nid
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
            elif existing[1] != message.folder_nid:
                moved_count += 1
                connection.execute(
                    """
                    UPDATE message
                    SET folder_nid = ?, last_seen_generation = ?
                    WHERE store_uid = ? AND nid = ?
                    """,
                    (message.folder_nid, generation, store_uid, message.nid),
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
            last_successful_sync TEXT NOT NULL,
            generation INTEGER NOT NULL
        );

        CREATE TABLE folder (
            store_uid TEXT NOT NULL REFERENCES store(uid),
            nid INTEGER NOT NULL,
            parent_nid INTEGER,
            name TEXT,
            path TEXT NOT NULL,
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
            body_format TEXT,
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
            PRIMARY KEY (store_uid, message_nid, index_in_message),
            FOREIGN KEY (store_uid, message_nid) REFERENCES message(store_uid, nid)
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
            store_uid, nid, parent_nid, name, path, last_seen_generation
        ) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(store_uid, nid) DO UPDATE SET
            parent_nid = excluded.parent_nid,
            name = excluded.name,
            path = excluded.path,
            last_seen_generation = excluded.last_seen_generation
        """,
        (
            store_uid,
            folder.nid,
            folder.parent_nid,
            folder.name,
            folder.path,
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
            attachment_count, body_raw, body_format, last_seen_generation
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            body_format = excluded.body_format,
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
            body_format,
            generation,
        ),
    )


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
    try:
        with sqlite3.connect(database_path) as connection:
            row = connection.execute(
                """
                SELECT source_path, source_size, source_mtime_ns, store_uid,
                       schema_version, generation
                FROM index_state WHERE singleton = 1
                """
            ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return _IndexState(_SourceState(row[0], row[1], row[2]), row[3], row[4], row[5])


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
            schema_version, last_successful_sync, generation
        ) VALUES (1, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(singleton) DO UPDATE SET
            source_path = excluded.source_path,
            source_size = excluded.source_size,
            source_mtime_ns = excluded.source_mtime_ns,
            store_uid = excluded.store_uid,
            schema_version = excluded.schema_version,
            last_successful_sync = excluded.last_successful_sync,
            generation = excluded.generation
        """,
        (
            source.path,
            source.size,
            source.mtime_ns,
            store_uid,
            SCHEMA_VERSION,
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


def _select_body(message: PstMessage) -> tuple[str | None, str | None]:
    for body, body_format in (
        (message.plain_text_body, "plain"),
        (message.html_body, "html"),
        (message.rtf_body, "rtf"),
    ):
        if body is not None:
            return body, body_format
    return None, None


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


def _format_time(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
