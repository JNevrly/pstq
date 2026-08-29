"""Disposable SQLite cache creation from normalized PST records."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from email import policy
from email.parser import HeaderParser
from pathlib import Path
from tempfile import NamedTemporaryFile

from pstq.pst import PstMessage, PstReader


@dataclass(frozen=True)
class ImportResult:
    """Counts written by one successful full cache import."""

    store_uid: str
    folder_count: int
    message_count: int


def import_pst(source_path: str | Path, database_path: str | Path) -> ImportResult:
    """Build DATABASE_PATH from SOURCE_PATH without risking its current contents.

    The temporary database is created beside the target so replacing the prior
    cache is atomic on the target filesystem.
    """
    target = Path(database_path)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent, delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

        result = _write_index(source_path, temporary_path)
        os.replace(temporary_path, target)
        return result
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _write_index(source_path: str | Path, database_path: Path) -> ImportResult:
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        _create_schema(connection)
        with connection, PstReader(source_path) as reader:
            store_uid = reader.store.uid
            connection.execute("INSERT INTO store (uid) VALUES (?)", (store_uid,))
            folder_count = 0
            message_count = 0
            for folder in reader.walk(include_bodies=True):
                connection.execute(
                    """
                    INSERT INTO folder (store_uid, nid, parent_nid, name, path)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        store_uid,
                        folder.nid,
                        folder.parent_nid,
                        folder.name,
                        folder.path,
                    ),
                )
                folder_count += 1
                for message in folder.messages:
                    _insert_message(connection, store_uid, message)
                    message_count += 1
    finally:
        connection.close()
    return ImportResult(
        store_uid=store_uid,
        folder_count=folder_count,
        message_count=message_count,
    )


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE store (
            uid TEXT PRIMARY KEY
        );

        CREATE TABLE folder (
            store_uid TEXT NOT NULL REFERENCES store(uid),
            nid INTEGER NOT NULL,
            parent_nid INTEGER,
            name TEXT,
            path TEXT NOT NULL,
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


def _insert_message(
    connection: sqlite3.Connection, store_uid: str, message: PstMessage
) -> None:
    body_raw, body_format = _select_body(message)
    relationships = _relationships(message.transport_headers)
    connection.execute(
        """
        INSERT INTO message (
            store_uid, nid, folder_nid, modification_time, subject, sender_name,
            client_submit_time, delivery_time, transport_headers, internet_message_id,
            in_reply_to, references_header, conversation_topic, conversation_index,
            attachment_count, body_raw, body_format
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        ),
    )


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
