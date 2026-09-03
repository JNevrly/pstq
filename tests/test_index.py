"""Tests for the disposable SQLite full-import cache."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from pstq import index
from pstq.pst import PstAttachment, PstFolder, PstMessage, PstReaderError, PstStore

REAL_SOURCE_STATE = index._source_state


def _message(
    *,
    nid: int = 3,
    folder_nid: int = 2,
    plain_text_body: str | bytes | None = "Plain body",
    html_body: str | bytes | None = "<p>HTML body</p>",
    rtf_body: str | bytes | None = "RTF body",
    attachments: tuple[PstAttachment, ...] = (),
    modification_time: datetime = datetime(2026, 8, 20, 12, 30),
) -> PstMessage:
    return PstMessage(
        nid=nid,
        folder_nid=folder_nid,
        modification_time=modification_time,
        subject="Status update",
        sender_name="Sender",
        client_submit_time=datetime(2026, 8, 20, 12),
        delivery_time=datetime(2026, 8, 20, 12, 30),
        transport_headers=(
            "Message-ID: <message@example.test>\n"
            "In-Reply-To: <parent@example.test>\n"
            "References: <root@example.test> <parent@example.test>\n"
        ),
        conversation_topic="Status",
        conversation_index="010203",
        attachment_count=1,
        plain_text_body=plain_text_body,
        rtf_body=rtf_body,
        html_body=html_body,
        attachments=attachments,
    )


class FakeReader:
    folders: tuple[PstFolder, ...] = ()
    error: Exception | None = None
    store_uid = "store"
    walk_arguments: list[dict[str, object]] = []
    attachment_calls: list[tuple[tuple[int, ...], int, int, int, Path]] = []
    body_calls: list[tuple[tuple[int, ...], int, int]] = []

    def __init__(self, _: str | Path) -> None:
        self.store = PstStore(self.store_uid)

    def __enter__(self) -> FakeReader:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def walk(
        self,
        *,
        include_bodies: bool = False,
        include_body_nids: frozenset[int] | set[int] | None = None,
    ):
        self.walk_arguments.append(
            {
                "include_bodies": include_bodies,
                "include_body_nids": include_body_nids,
            }
        )
        for folder in self.folders:
            yield folder
        if self.error is not None:
            raise self.error

    def extract_attachment(
        self,
        folder_indexes: tuple[int, ...],
        message_index: int,
        message_nid: int,
        attachment_index: int,
        output_path: Path,
    ) -> int:
        self.attachment_calls.append(
            (
                folder_indexes,
                message_index,
                message_nid,
                attachment_index,
                output_path,
            )
        )
        output_path.write_bytes(b"anonymous attachment")
        return len(b"anonymous attachment")

    def read_message_body(
        self,
        folder_indexes: tuple[int, ...],
        message_index: int,
        message_nid: int,
    ) -> tuple[str | bytes | None, str | None]:
        self.body_calls.append((folder_indexes, message_index, message_nid))
        folder = next(folder for folder in self.folders if folder.parent_nid is None)
        for folder_index in folder_indexes:
            folder = next(
                child
                for child in self.folders
                if child.parent_nid == folder.nid
                and child.index_in_parent == folder_index
            )
        message = next(
            item for item in folder.messages if item.index_in_folder == message_index
        )
        if message.nid != message_nid:
            raise PstReaderError(
                f"Cached locator does not match message {message_nid}."
            )
        return index._select_body(message)


def _records(*messages: PstMessage) -> tuple[PstFolder, ...]:
    return (
        PstFolder(
            nid=1,
            parent_nid=None,
            name="Root",
            path="Root",
            messages=(),
        ),
        PstFolder(
            nid=2,
            parent_nid=1,
            name="Inbox",
            path="Root/Inbox",
            messages=messages,
            index_in_parent=0,
        ),
    )


@pytest.fixture(autouse=True)
def fake_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeReader.error = None
    FakeReader.store_uid = "store"
    FakeReader.walk_arguments = []
    FakeReader.attachment_calls = []
    FakeReader.body_calls = []
    FakeReader.folders = _records(_message())
    monkeypatch.setattr(index, "PstReader", FakeReader)
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])


def _rows(path: Path, statement: str) -> list[tuple[object, ...]]:
    with sqlite3.connect(path) as connection:
        return connection.execute(statement).fetchall()


def test_import_pst_creates_normalized_cache(tmp_path: Path) -> None:
    database_path = tmp_path / "index.sqlite"

    result = index.import_pst("archive.pst", database_path)

    assert result == index.ImportResult("store", folder_count=2, message_count=1)
    assert FakeReader.walk_arguments == [
        {"include_bodies": True, "include_body_nids": None}
    ]
    assert _rows(database_path, "SELECT uid FROM store") == [("store",)]
    assert _rows(
        database_path,
        "SELECT store_uid, nid, parent_nid, name, path, index_in_parent "
        "FROM folder ORDER BY nid",
    ) == [
        ("store", 1, None, "Root", "Root", None),
        ("store", 2, 1, "Inbox", "Root/Inbox", 0),
    ]
    assert _rows(
        database_path,
        """
        SELECT nid, folder_nid, modification_time, subject, sender_name,
               client_submit_time, delivery_time, body_clean, body_format,
               internet_message_id, in_reply_to, references_header,
               conversation_topic, conversation_index, attachment_count, index_in_folder
        FROM message
        """,
    ) == [
        (
            3,
            2,
            "2026-08-20T12:30:00",
            "Status update",
            "Sender",
            "2026-08-20T12:00:00",
            "2026-08-20T12:30:00",
            "Plain body",
            "plain",
            "<message@example.test>",
            "<parent@example.test>",
            "<root@example.test> <parent@example.test>",
            "Status",
            "010203",
            1,
            0,
        )
    ]
    assert _rows(database_path, "SELECT * FROM recipient") == []
    assert _rows(database_path, "SELECT * FROM attachment") == []
    state = _rows(
        database_path,
        """
        SELECT source_path, source_size, source_mtime_ns, store_uid, schema_version,
               last_successful_sync
        FROM index_state
        """,
    )
    assert state[0][:5] == ("archive.pst", 1, 1, "store", index.SCHEMA_VERSION)
    assert state[0][5]


def test_import_pst_indexes_thread_relationship_metadata(tmp_path: Path) -> None:
    database_path = tmp_path / "index.sqlite"

    index.import_pst("archive.pst", database_path)

    assert _rows(
        database_path,
        """
        SELECT message_nid, identifier, relation_type
        FROM message_relation
        ORDER BY identifier, relation_type
        """,
    ) == [
        (3, "<message@example.test>", 1),
        (3, "<parent@example.test>", 0),
        (3, "<root@example.test>", 0),
    ]
    assert _rows(
        database_path,
        "SELECT conversation_topic_key, conversation_root FROM message",
    ) == [("status", None)]
    message_indexes = {
        row[1] for row in _rows(database_path, "PRAGMA index_list('message')")
    }
    relation_indexes = {
        row[1] for row in _rows(database_path, "PRAGMA index_list('message_relation')")
    }
    assert {
        "message_conversation_root",
        "message_conversation_topic_key",
    } <= message_indexes
    assert "message_relation_identifier" in relation_indexes


def test_import_pst_prefers_mapi_relationship_values_and_falls_back_to_headers(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "index.sqlite"
    FakeReader.folders = _records(
        replace(
            _message(),
            internet_message_id="<mapi@example.test>",
            in_reply_to="<mapi-parent@example.test>",
            references_header="<mapi-root@example.test>",
            conversation_topic=None,
            conversation_index=None,
            transport_headers=(
                "Message-ID: <header@example.test>\n"
                "Thread-Topic: Header topic\n"
                "Thread-Index: AQID\n"
            ),
        )
    )

    index.import_pst("archive.pst", database_path)

    assert _rows(
        database_path,
        """
        SELECT internet_message_id, in_reply_to, references_header,
               conversation_topic, conversation_index
        FROM message
        """,
    ) == [
        (
            "<mapi@example.test>",
            "<mapi-parent@example.test>",
            "<mapi-root@example.test>",
            "Header topic",
            "010203",
        )
    ]


def _thread_message(
    nid: int,
    *,
    headers: str | None,
    body: str,
    delivery_time: datetime | None,
    client_submit_time: datetime | None = None,
    conversation_topic: str | None = None,
    conversation_index: str | None = None,
) -> PstMessage:
    return replace(
        _message(nid=nid),
        transport_headers=headers,
        plain_text_body=body,
        html_body=None,
        rtf_body=None,
        delivery_time=delivery_time,
        client_submit_time=client_submit_time,
        conversation_topic=conversation_topic,
        conversation_index=conversation_index,
    )


def test_get_thread_follows_transitive_header_relations_and_keeps_bodies_separate(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "index.sqlite"
    FakeReader.folders = _records(
        _thread_message(
            10,
            headers="Message-ID: <root@example.test>",
            body="Root contribution",
            delivery_time=datetime(2026, 8, 20, 10),
            conversation_topic="Generic status",
        ),
        _thread_message(
            11,
            headers=(
                "Message-ID: <parent@example.test>\nIn-Reply-To: <root@example.test>\n"
            ),
            body="Parent contribution",
            delivery_time=datetime(2026, 8, 20, 11),
            conversation_topic="Generic status",
        ),
        _thread_message(
            12,
            headers=(
                "Message-ID: <reply@example.test>\n"
                "References: <root@example.test> <parent@example.test>\n"
            ),
            body="Reply contribution",
            delivery_time=datetime(2026, 8, 20, 12),
            conversation_topic="Generic status",
        ),
        _thread_message(
            13,
            headers="Message-ID: <unrelated@example.test>",
            body="Unrelated contribution",
            delivery_time=datetime(2026, 8, 20, 13),
            conversation_topic="Generic status",
        ),
    )
    index.import_pst("archive.pst", database_path)

    result = index.get_thread(database_path, "store:11")

    assert result["id"] == "store:11"
    assert [message["id"] for message in result["messages"]] == [
        "store:10",
        "store:11",
        "store:12",
    ]
    assert [message["body"] for message in result["messages"]] == [
        "Root contribution",
        "Parent contribution",
        "Reply contribution",
    ]


def test_get_thread_queries_the_indexed_relationship_component(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "index.sqlite"
    FakeReader.folders = _records(
        _thread_message(
            10,
            headers="Message-ID: <root@example.test>",
            body="Root",
            delivery_time=datetime(2026, 8, 20, 10),
        ),
        _thread_message(
            11,
            headers=(
                "Message-ID: <reply@example.test>\nIn-Reply-To: <root@example.test>"
            ),
            body="Reply",
            delivery_time=datetime(2026, 8, 20, 11),
        ),
        *(
            _thread_message(
                nid,
                headers=f"Message-ID: <unrelated-{nid}@example.test>",
                body="Unrelated",
                delivery_time=datetime(2026, 8, 20, 12),
            )
            for nid in range(12, 112)
        ),
    )
    index.import_pst("archive.pst", database_path)
    statements: list[str] = []
    original_connect = sqlite3.connect

    def traced_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = original_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(index.sqlite3, "connect", traced_connect)

    result = index.get_thread(database_path, "store:11")

    assert [message["id"] for message in result["messages"]] == [
        "store:10",
        "store:11",
    ]
    assert any("FROM member" in statement for statement in statements)
    assert any("message_relation AS current" in statement for statement in statements)
    assert not any(
        "internet_message_id, in_reply_to, references_header" in statement
        for statement in statements
    )


def test_get_thread_uses_conversation_index_then_topic_as_conservative_fallbacks(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "index.sqlite"
    root = "ab" * 22
    FakeReader.folders = _records(
        _thread_message(
            20,
            headers=None,
            body="First indexed contribution",
            delivery_time=datetime(2026, 8, 20, 10),
            conversation_topic="Shared topic",
            conversation_index=f"{root}0102030405",
        ),
        _thread_message(
            21,
            headers=None,
            body="Second indexed contribution",
            delivery_time=datetime(2026, 8, 20, 11),
            conversation_topic="Shared topic",
            conversation_index=f"{root}060708090a",
        ),
        _thread_message(
            22,
            headers=None,
            body="Same topic but another thread",
            delivery_time=datetime(2026, 8, 20, 12),
            conversation_topic="Shared topic",
            conversation_index="cd" * 22,
        ),
    )
    index.import_pst("archive.pst", database_path)

    indexed = index.get_thread(database_path, "store:20")

    assert [message["id"] for message in indexed["messages"]] == [
        "store:20",
        "store:21",
    ]

    FakeReader.folders = _records(
        _thread_message(
            30,
            headers="Message-ID: malformed",
            body="Topic one",
            delivery_time=datetime(2026, 8, 20, 10),
            conversation_topic="Topic fallback",
            conversation_index="not-hex",
        ),
        _thread_message(
            31,
            headers=None,
            body="Topic two",
            delivery_time=datetime(2026, 8, 20, 11),
            conversation_topic=" topic FALLBACK ",
        ),
        _thread_message(
            32,
            headers=None,
            body="Different topic",
            delivery_time=datetime(2026, 8, 20, 12),
            conversation_topic="Other topic",
        ),
    )
    index.import_pst("archive.pst", database_path)

    topic = index.get_thread(database_path, "store:30")

    assert [message["id"] for message in topic["messages"]] == [
        "store:30",
        "store:31",
    ]


def test_get_thread_orders_dates_deterministically_and_returns_partial_anchor(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "index.sqlite"
    FakeReader.folders = _records(
        _thread_message(
            42,
            headers="Message-ID: <late@example.test>\nIn-Reply-To: <root@example.test>",
            body="Late",
            delivery_time=datetime(2026, 8, 20, 12, tzinfo=UTC),
        ),
        _thread_message(
            41,
            headers=(
                "Message-ID: <early@example.test>\nIn-Reply-To: <root@example.test>"
            ),
            body="Early",
            delivery_time=datetime(
                2026, 8, 20, 12, tzinfo=timezone(timedelta(hours=2))
            ),
        ),
        _thread_message(
            40,
            headers="Message-ID: <root@example.test>",
            body="Root",
            delivery_time=None,
            client_submit_time=None,
        ),
        _thread_message(
            43,
            headers="Message-ID: malformed",
            body="Partial",
            delivery_time=None,
            client_submit_time=None,
            conversation_topic=None,
            conversation_index="bad",
        ),
    )
    index.import_pst("archive.pst", database_path)

    threaded = index.get_thread(database_path, "store:42")
    partial = index.get_thread(database_path, "store:43")

    assert [message["id"] for message in threaded["messages"]] == [
        "store:41",
        "store:42",
        "store:40",
    ]
    assert [message["id"] for message in partial["messages"]] == ["store:43"]
    with pytest.raises(ValueError, match="does not belong"):
        index.get_thread(database_path, "other:42")
    with pytest.raises(ValueError, match="Message not found"):
        index.get_thread(database_path, "store:99")


def test_thread_includes_deduplicated_owner_history_and_suppresses_native_duplicates(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "index.sqlite"
    quoted = (
        "-----Original Message-----\nFrom: Owner <owner@example.test>\n"
        "Sent: 20.08.2026 10:00\nTo: Recipient <recipient@example.test>\n"
        "Subject: Re: Status\nRecovered contribution"
    )
    FakeReader.folders = _records(
        _thread_message(
            10,
            headers="Message-ID: <root@example.test>",
            body="Root contribution",
            delivery_time=datetime(2026, 8, 20, 9),
        ),
        _thread_message(
            11,
            headers=(
                "Message-ID: <reply@example.test>\nIn-Reply-To: <root@example.test>"
            ),
            body=f"Current reply\n{quoted}",
            delivery_time=datetime(2026, 8, 20, 11),
        ),
        _thread_message(
            12,
            headers=(
                "Message-ID: <later@example.test>\nIn-Reply-To: <root@example.test>"
            ),
            body=f"Later reply\n{quoted}",
            delivery_time=datetime(2026, 8, 20, 12),
        ),
    )

    index.import_pst(
        "archive.pst",
        database_path,
        index.HistorySettings(("owner@example.test",), (), "Europe/Prague"),
    )

    result = index.get_thread(database_path, "store:11")

    recovered_records = [
        message for message in result["messages"] if ":q:" in str(message["id"])
    ]
    assert len(recovered_records) == 1
    recovered = recovered_records[0]
    assert recovered["body"] == "Recovered contribution"
    assert recovered["date"] == "2026-08-20T10:00:00+02:00"
    assert recovered["folder"] == "Root/Inbox"
    assert not {"provenance", "record_type", "relation"} & recovered.keys()
    matches = index.search_messages(database_path, "Recovered")
    assert [match.id for match in matches] == [recovered["id"]]
    assert matches[0].as_dict() == {
        "date": "2026-08-20T10:00:00+02:00",
        "from": "Owner <owner@example.test>",
        "id": recovered["id"],
        "folder": "Root/Inbox",
        "score": matches[0].score,
        "snippet": "Recovered contribution",
        "subject": "Re: Status",
        "to": ["recipient@example.test"],
    }
    assert index.get_message(database_path, recovered["id"]) == recovered
    assert (
        index.get_full_message(
            "archive.pst",
            database_path,
            recovered["id"],
            index.HistorySettings(("owner@example.test",), (), "Europe/Prague"),
        )
        == recovered
    )
    assert FakeReader.body_calls == []
    assert recovered["id"] in [
        message["id"]
        for message in index.get_thread(database_path, recovered["id"])["messages"]
    ]
    assert index.list_attachments(database_path, recovered["id"]) == []

    FakeReader.folders = _records(
        replace(
            _thread_message(
                20,
                headers=(
                    "Message-ID: <native@example.test>\n"
                    "From: Owner <owner@example.test>"
                ),
                body="Recovered contribution",
                delivery_time=datetime(2026, 8, 20, 10),
            ),
            subject="Status",
        ),
        _thread_message(
            21,
            headers=(
                "Message-ID: <quote@example.test>\nIn-Reply-To: <native@example.test>"
            ),
            body=f"Current reply\n{quoted}",
            delivery_time=datetime(2026, 8, 20, 11),
        ),
    )
    index.import_pst(
        "archive.pst",
        database_path,
        index.HistorySettings(("owner@example.test",), (), "Europe/Prague"),
    )

    messages = index.get_thread(database_path, "store:21")["messages"]
    assert [message["id"] for message in messages] == [
        "store:20",
        "store:21",
    ]
    assert [
        result.id for result in index.search_messages(database_path, "Recovered")
    ] == ["store:20"]


def test_unified_search_orders_and_filters_recovered_results(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "index.sqlite"
    alpha = (
        "-----Original Message-----\nFrom: Owner <owner@example.test>\n"
        "Sent: 20.08.2026 10:00\nTo: Recipient <recipient@example.test>\n"
        "Subject: Alpha\nCommon recovery alpha"
    )
    beta = (
        "-----Original Message-----\nFrom: Owner <owner@example.test>\n"
        "Sent: 21.08.2026 10:00\nTo: Recipient <recipient@example.test>\n"
        "Subject: Beta\nCommon recovery beta"
    )
    FakeReader.folders = (
        PstFolder(1, None, "Root", "Root", ()),
        PstFolder(
            2,
            1,
            "Inbox",
            "Root/Inbox",
            (
                _message(nid=3, plain_text_body="Common native contribution"),
                _message(nid=4, plain_text_body=f"Current\n{alpha}"),
            ),
            index_in_parent=0,
        ),
        PstFolder(
            6,
            1,
            "Archive",
            "Root/Archive",
            (
                _message(nid=5, folder_nid=6, plain_text_body=f"Repeated\n{alpha}"),
                _message(nid=7, folder_nid=6, plain_text_body=f"Later\n{beta}"),
            ),
            index_in_parent=1,
        ),
    )
    history = index.HistorySettings(("owner@example.test",), (), "Europe/Prague")
    index.import_pst("archive.pst", database_path, history)

    results = index.search_messages(database_path, "Common")

    assert results == index.search_messages(database_path, "Common")
    assert index.search_messages(database_path, "Common", limit=1) == results[:1]
    assert (
        index.search_messages(database_path, "Common", limit=1, offset=1)
        == results[1:2]
    )
    assert len(results) == 3
    assert {result.subject for result in results} == {"Status update", "Alpha", "Beta"}
    by_subject = {result.subject: result for result in results}
    assert by_subject["Alpha"].folder == "Root/Inbox"
    assert by_subject["Beta"].folder == "Root/Archive"
    assert [
        result.subject
        for result in index.search_messages(
            database_path, "recovery", folder="Root/Inbox"
        )
    ] == ["Alpha"]
    assert [
        result.subject
        for result in index.search_messages(
            database_path, "recovery", folder="Root/Archive"
        )
    ] == ["Beta"]
    assert [
        result.id
        for result in index.search_messages(
            database_path, "Common", has_attachment=True
        )
    ] == ["store:3"]
    assert {
        result.subject
        for result in index.search_messages(
            database_path,
            "recovery",
            sender_aliases=("owner@example.test", "Owner"),
            recipient="recipient@example.test",
            after="2026-08-20T00:00:00",
            before="2026-08-22T00:00:00",
        )
    } == {"Alpha", "Beta"}
    with pytest.raises(ValueError, match="must not be empty"):
        index.search_messages(database_path, " ")
    with pytest.raises(ValueError, match="offset must be zero"):
        index.search_messages(database_path, "Common", offset=-1)
    with pytest.raises(ValueError, match="requires QUERY or at least one"):
        index.search_messages(database_path, None)
    with pytest.raises(ValueError, match="Invalid FTS query"):
        index.search_messages(database_path, '"')


def test_filter_only_searches_apply_structured_filters_in_date_order(
    tmp_path: Path,
) -> None:
    first = replace(
        _message(),
        delivery_time=datetime(2026, 8, 20, 12, 30),
        transport_headers="To: Recipient <recipient@example.test>\n",
    )
    second = replace(
        _message(nid=4),
        delivery_time=datetime(2026, 8, 21, 12, 30),
        index_in_folder=1,
        transport_headers="To: Recipient <recipient@example.test>\n",
    )
    FakeReader.folders = _records(first, second)
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)

    results = index.search_messages(
        database_path,
        None,
        sender="sender",
        recipient="recipient@example.test",
        after="2026-08-20T00:00:00",
        before="2026-08-22T00:00:00",
        folder="Root/Inbox",
        has_attachment=True,
    )

    assert [result.id for result in results] == ["store:4", "store:3"]
    assert [(result.score, result.snippet) for result in results] == [
        (0.0, ""),
        (0.0, ""),
    ]
    assert [
        result.id
        for result in index.search_messages(
            database_path, None, sender_aliases=("Sender",)
        )
    ] == ["store:4", "store:3"]


def test_search_messages_paginates_full_text_and_filter_only_results(
    tmp_path: Path,
) -> None:
    messages = tuple(
        replace(
            _message(nid=nid, plain_text_body="Pagination result"),
            delivery_time=datetime(2026, 8, 20, 12),
            index_in_folder=nid,
        )
        for nid in range(10, 15)
    )
    FakeReader.folders = _records(*messages)
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)

    full_text = index.search_messages(database_path, "Pagination", limit=20)
    full_text_pages = [
        index.search_messages(database_path, "Pagination", limit=2, offset=offset)
        for offset in (0, 2, 4)
    ]
    filter_only = index.search_messages(database_path, None, sender="Sender", limit=20)
    filter_only_pages = [
        index.search_messages(
            database_path, None, sender="Sender", limit=2, offset=offset
        )
        for offset in (0, 2, 4)
    ]

    assert [result.id for page in full_text_pages for result in page] == [
        result.id for result in full_text
    ]
    assert [result.id for page in filter_only_pages for result in page] == [
        result.id for result in filter_only
    ]
    assert [result.id for result in full_text] == [
        "store:10",
        "store:11",
        "store:12",
        "store:13",
        "store:14",
    ]
    assert [result.id for result in filter_only] == [
        "store:10",
        "store:11",
        "store:12",
        "store:13",
        "store:14",
    ]
    assert [len(page) for page in full_text_pages] == [2, 2, 1]
    assert [len(page) for page in filter_only_pages] == [2, 2, 1]
    assert full_text == index.search_messages(database_path, "Pagination", limit=20)


def test_incremental_sync_removes_recovered_search_documents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    quoted = (
        "-----Original Message-----\nFrom: Owner <owner@example.test>\n"
        "Sent: 20.08.2026 10:00\nTo: Recipient\nSubject: Status\nRecovered"
    )
    history = index.HistorySettings(("owner@example.test",), (), "UTC")
    FakeReader.folders = _records(_message(plain_text_body=f"Current\n{quoted}"))
    index.import_pst("archive.pst", database_path, history)
    assert index.search_messages(database_path, "Recovered")

    FakeReader.folders = _records(
        _message(
            plain_text_body="Current without quoted history",
            modification_time=datetime(2026, 8, 21, 12, 30),
        )
    )
    source[0] = index._SourceState("archive.pst", 2, 2)
    result = index.sync_pst("archive.pst", database_path, history)

    assert result.full is False
    assert index.search_messages(database_path, "Recovered") == []
    assert _rows(
        database_path,
        "SELECT COUNT(*) FROM search_document WHERE recovered_fingerprint IS NOT NULL",
    ) == [(0,)]


def test_incremental_sync_reuses_cached_quotes_and_global_deduplication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    alpha = (
        "-----Original Message-----\nFrom: Owner <owner@example.test>\n"
        "Sent: 20.08.2026 10:00\nTo: Recipient\nSubject: Alpha\nCommon alpha"
    )
    beta = (
        "-----Original Message-----\nFrom: Owner <owner@example.test>\n"
        "Sent: 21.08.2026 10:00\nTo: Recipient\nSubject: Beta\nCommon beta"
    )
    history = index.HistorySettings(("owner@example.test",), (), "UTC")
    FakeReader.folders = _records(
        _message(nid=3, plain_text_body="Current native message"),
        _message(nid=4, plain_text_body=f"Current\n{alpha}"),
        _message(nid=5, plain_text_body=f"Current\n{beta}"),
    )
    index.import_pst("archive.pst", database_path, history)

    analyzed: list[str | bytes | None] = []
    rendered: list[str | bytes | None] = []
    analyze_body = index.analyze_body
    render_body = index._render_body

    def counting_analyze(body: str | bytes | None, timezone_name: str):
        analyzed.append(body)
        return analyze_body(body, timezone_name)

    def counting_render(
        body: str | bytes | None,
        body_format: str | None,
        attachment_ids: dict[str, str],
    ) -> str | bytes | None:
        rendered.append(body)
        return render_body(body, body_format, attachment_ids)

    monkeypatch.setattr(index, "analyze_body", counting_analyze)
    monkeypatch.setattr(index, "_render_body", counting_render)
    FakeReader.folders = _records(
        replace(
            _message(nid=3, plain_text_body="Common alpha"),
            modification_time=datetime(2026, 8, 21, 12, 30),
            sender_name="Owner",
            subject="Alpha",
            transport_headers="From: Owner <owner@example.test>\n",
        ),
        _message(nid=4, plain_text_body=f"Current\n{alpha}"),
        _message(nid=5, plain_text_body=f"Current\n{beta}"),
    )
    source[0] = index._SourceState("archive.pst", 2, 2)

    result = index.sync_pst("archive.pst", database_path, history)

    assert result.modified_count == 1
    assert analyzed == ["Common alpha"]
    assert rendered == ["Common alpha"]
    assert _rows(
        database_path,
        "SELECT subject FROM recovered_message ORDER BY subject",
    ) == [("Beta",)]
    assert _rows(
        database_path,
        "SELECT source_message_nid FROM quote_occurrence",
    ) == [(5,)]
    assert {
        result.subject for result in index.search_messages(database_path, "Common")
    } == {
        "Alpha",
        "Beta",
    }


def test_thread_parsers_ignore_malformed_values() -> None:
    assert index._thread_index("not base64") is None
    assert index._conversation_root("zz" * 22) is None
    assert index._thread_order((1, None, None, None, None, "bad", None)) == (
        1,
        datetime.max,
        1,
    )
    assert index._thread_order(
        (1, None, None, None, None, "2026-08-20T12:00:00+02:00", None)
    ) == (0, datetime(2026, 8, 20, 10), 1)
    assert index._record_order({"date": "bad", "id": "store:q:x"}) == (
        1,
        datetime.max,
        "store:q:x",
    )
    assert index._header_sender_email(None) is None
    assert index._normalized_name(" Owner  Name ") == "owner name"


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (_message(plain_text_body=None), ("HTML body", "html")),
        (_message(plain_text_body=None, html_body=None), ("RTF body", "rtf")),
        (_message(plain_text_body=None, html_body=None, rtf_body=None), (None, None)),
    ],
)
def test_import_pst_selects_the_best_available_body(
    tmp_path: Path, message: PstMessage, expected: tuple[str | None, str | None]
) -> None:
    FakeReader.folders = _records(message)
    database_path = tmp_path / "index.sqlite"

    index.import_pst("archive.pst", database_path)

    assert _rows(database_path, "SELECT body_clean, body_format FROM message") == [
        expected
    ]


def test_import_pst_renders_html_with_safe_image_markers(tmp_path: Path) -> None:
    attachment = PstAttachment(
        index=0,
        filename="chart.png",
        mime_type="image/png",
        size=12,
        content_id="<chart@example.test>",
        content_location=None,
        attachment_method=1,
        hidden=True,
        rendering_position=None,
    )
    FakeReader.folders = _records(
        _message(
            plain_text_body=None,
            html_body=(
                "<p>Current update <img src='cid:chart@example.test'></p>"
                "<img src='https://example.test/" + "a" * 121 + "'>"
                "<img src='data:image/png;base64,secret'><img src='cid:missing'>"
                "<script>hidden()</script>"
                "<p>-----Original Message-----</p><p>Quoted</p>"
            ),
            attachments=(attachment,),
        )
    )
    database_path = tmp_path / "index.sqlite"

    index.import_pst("archive.pst", database_path)

    assert _rows(database_path, "SELECT body_clean FROM message") == [
        (
            "Current update [attachment: store:3:0]\n"
            "[image: remote "
            + index._bounded("https://example.test/" + "a" * 121)
            + "][image: embedded data][image: unresolved cid:missing]\n",
        )
    ]


def test_recovered_cid_image_uses_a_canonical_source_attachment(tmp_path: Path) -> None:
    attachment = PstAttachment(
        index=0,
        filename="photo.png",
        mime_type="image/png",
        size=20,
        content_id="<photo@example.test>",
        content_location=None,
        attachment_method=1,
        hidden=True,
        rendering_position=0,
    )
    FakeReader.folders = _records(
        _message(
            plain_text_body=None,
            html_body=(
                "<p>Current</p><p>-----Original Message-----</p>"
                "<p>From: Owner &lt;owner@example.test&gt;</p>"
                "<p>Sent: 20.08.2026 10:00</p><p>To: Recipient</p>"
                "<p>Subject: Status</p>"
                "<p><img src='CID:&lt;PHOTO@EXAMPLE.TEST&gt;'></p>"
            ),
            attachments=(attachment,),
        )
    )
    database_path = tmp_path / "index.sqlite"
    output_path = tmp_path / "photo.png"
    history = index.HistorySettings(("owner@example.test",), (), "UTC")

    index.import_pst("archive.pst", database_path, history)

    recovered = index.search_messages(database_path, "attachment")
    assert len(recovered) == 1
    assert index.get_message(database_path, recovered[0].id)["body"] == (
        "[attachment: store:3:0]"
    )
    assert index.list_attachments(database_path, recovered[0].id) == []
    assert index.extract_attachment(
        "archive.pst", database_path, "store:3:0", output_path, history
    ) == len(b"anonymous attachment")
    assert output_path.read_bytes() == b"anonymous attachment"


@pytest.mark.parametrize(
    "attachments",
    [
        (
            PstAttachment(
                0,
                "photo@example.test",
                "image/png",
                20,
                None,
                "photo@example.test",
                1,
                True,
                0,
            ),
        ),
        (
            PstAttachment(
                0,
                "photo.png",
                "image/png",
                20,
                "<photo@example.test>",
                None,
                1,
                True,
                0,
            ),
            PstAttachment(
                1,
                "photo-copy.png",
                "image/png",
                20,
                "PHOTO@EXAMPLE.TEST",
                None,
                1,
                True,
                1,
            ),
        ),
    ],
)
def test_recovered_cid_image_requires_unambiguous_content_id(
    tmp_path: Path, attachments: tuple[PstAttachment, ...]
) -> None:
    html_body = (
        "<p>Current</p><p>-----Original Message-----</p>"
        "<p>From: Owner &lt;owner@example.test&gt;</p>"
        "<p>Sent: 20.08.2026 10:00</p><p>To: Recipient</p><p>Subject: Status</p>"
        "<p><img src='cid:&lt;photo@example.test&gt;'></p>"
    )
    FakeReader.folders = _records(
        _message(
            nid=3, plain_text_body=None, html_body=html_body, attachments=attachments
        )
    )
    database_path = tmp_path / "index.sqlite"

    index.import_pst(
        "archive.pst",
        database_path,
        index.HistorySettings(("owner@example.test",), (), "UTC"),
    )

    recovered = index.search_messages(database_path, "unresolved")
    assert len(recovered) == 1
    assert index.get_message(database_path, recovered[0].id)["body"] == (
        "[image: unresolved cid:<photo@example.test>]"
    )


def test_recovered_cid_image_uses_only_the_lowest_nid_canonical_source(
    tmp_path: Path,
) -> None:
    html_body = (
        "<p>Current</p><p>-----Original Message-----</p>"
        "<p>From: Owner &lt;owner@example.test&gt;</p>"
        "<p>Sent: 20.08.2026 10:00</p><p>To: Recipient</p><p>Subject: Status</p>"
        "<p><img src='cid:photo@example.test'></p>"
    )
    attachment = PstAttachment(
        0, "photo.png", "image/png", 20, "<photo@example.test>", None, 1, True, 0
    )
    FakeReader.folders = _records(
        _message(nid=3, plain_text_body=None, html_body=html_body),
        _message(
            nid=4, plain_text_body=None, html_body=html_body, attachments=(attachment,)
        ),
    )
    database_path = tmp_path / "index.sqlite"

    index.import_pst(
        "archive.pst",
        database_path,
        index.HistorySettings(("owner@example.test",), (), "UTC"),
    )

    recovered = index.search_messages(database_path, "unresolved")
    assert len(recovered) == 1
    assert index.get_message(database_path, recovered[0].id)["body"] == (
        "[image: unresolved cid:photo@example.test]"
    )


def test_sync_rebuilds_recovered_cid_images_when_attachments_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    html_body = (
        "<p>Current</p><p>-----Original Message-----</p>"
        "<p>From: Owner &lt;owner@example.test&gt;</p>"
        "<p>Sent: 20.08.2026 10:00</p><p>To: Recipient</p><p>Subject: Status</p>"
        "<p><img src='cid:photo@example.test'></p>"
    )
    history = index.HistorySettings(("owner@example.test",), (), "UTC")
    database_path = tmp_path / "index.sqlite"
    matching = PstAttachment(
        0, "photo.png", "image/png", 20, "<photo@example.test>", None, 1, True, 0
    )
    changed = PstAttachment(
        0, "photo.png", "image/png", 20, "<other@example.test>", None, 1, True, 0
    )
    FakeReader.folders = _records(
        _message(
            nid=3, plain_text_body=None, html_body=html_body, attachments=(matching,)
        )
    )
    index.import_pst("archive.pst", database_path, history)
    recovered_id = index.search_messages(database_path, "attachment")[0].id

    source[0] = index._SourceState("archive.pst", 2, 2)
    FakeReader.folders = _records(
        _message(
            nid=3,
            plain_text_body=None,
            html_body=html_body,
            attachments=(changed,),
            modification_time=datetime(2026, 8, 21, 12, 30),
        )
    )
    result = index.sync_pst("archive.pst", database_path, history)

    assert result.full is False
    assert index.get_message(database_path, recovered_id)["body"] == (
        "[image: unresolved cid:photo@example.test]"
    )

    FakeReader.folders = _records(
        _message(
            nid=3, plain_text_body=None, html_body=html_body, attachments=(matching,)
        )
    )
    result = index.sync_pst("archive.pst", database_path, history, full=True)

    assert result.full is True
    assert index.get_message(database_path, recovered_id)["body"] == (
        "[attachment: store:3:0]"
    )


def test_html_renderer_handles_empty_and_block_tags() -> None:
    assert index._render_body("<div>A<br>B</div><style>x</style>", "html", {}) == "A\nB"
    assert index._render_body(b"<p>Bytes</p>", "html", {}) == "Bytes"
    assert index._render_body("plain", "plain", {}) == "plain"
    assert index._image_marker(None, {}) == "[image: missing source]"
    assert index._image_marker(" CID:<MATCH> ", {"match": "store:3:0"}) == (
        "[attachment: store:3:0]"
    )
    renderer = index._HtmlBodyRenderer({})
    renderer.handle_starttag("script", [])
    renderer.handle_starttag("p", [])
    renderer.handle_endtag("script")
    renderer.handle_startendtag("img", [])
    assert renderer.rendered() == "[image: missing source]"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "Current update.\n\n-----Original Message-----\nQuoted history.",
            "Current update.\n\n",
        ),
        (
            "Current update.\nFrom: Sender <sender@example.test>\n"
            "Sent: Monday, August 24, 2026 9:00 AM\n"
            "To: Recipient <recipient@example.test>\n"
            "Cc: Copy <copy@example.test>\n"
            "Subject: Previous update\nQuoted history.",
            "Current update.\n",
        ),
    ],
)
def test_clean_body_removes_recognized_outlook_reply_history(
    body: str, expected: str
) -> None:
    assert index.clean_body(body) == expected


def test_clean_body_keeps_ambiguous_content_searchable(tmp_path: Path) -> None:
    body = (
        "Draft a header example.\nFrom: example sender\n"
        "To: example recipient\nSubject: searchable ambiguous content"
    )
    FakeReader.folders = _records(_message(plain_text_body=body))
    database_path = tmp_path / "index.sqlite"

    index.import_pst("archive.pst", database_path)

    assert index.clean_body(body) == body
    assert index.clean_body("From: sender\nSent: today\nTo: recipient") == (
        "From: sender\nSent: today\nTo: recipient"
    )
    assert index.clean_body("From: sender") == "From: sender"
    assert index.clean_body(None) is None
    assert index.clean_body(b"byte body") == "byte body"
    assert index.search_messages(database_path, "ambiguous")


def test_import_omits_raw_body_and_indexes_cleaned_body(tmp_path: Path) -> None:
    body = "Current content.\n-----Original Message-----\nQuoted content."
    FakeReader.folders = _records(_message(plain_text_body=body))
    database_path = tmp_path / "index.sqlite"

    index.import_pst("archive.pst", database_path)

    rows = _rows(database_path, "SELECT body_clean, body_format FROM message")
    assert rows == [("Current content.\n", "plain")]
    assert "body_raw" not in {
        row[1] for row in _rows(database_path, "PRAGMA table_info(message)")
    }
    assert index.get_message(database_path, "store:3")["body"] == "Current content.\n"
    assert index.search_messages(database_path, "Current")
    assert index.search_messages(database_path, "Quoted") == []


def test_get_full_message_reads_the_current_source_body(tmp_path: Path) -> None:
    cached = "Cached content.\n-----Original Message-----\nQuoted content."
    source = "Current source content.\n-----Original Message-----\nQuoted content."
    FakeReader.folders = _records(_message(plain_text_body=cached))
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    FakeReader.folders = _records(_message(plain_text_body=source))

    message = index.get_full_message("archive.pst", database_path, "store:3")

    assert message["body"] == source
    assert message["body_format"] == "plain"
    assert index.get_message(database_path, "store:3")["body"] == "Cached content.\n"
    assert FakeReader.body_calls == [((0,), 0, 3)]


def test_get_full_message_synchronizes_reordered_locators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    message = _message(plain_text_body="Current source body")
    FakeReader.folders = _records(message)
    index.import_pst("archive.pst", database_path)
    source[0] = index._SourceState("archive.pst", 2, 2)
    FakeReader.folders = (
        PstFolder(1, None, "Root", "Root", ()),
        PstFolder(
            2,
            1,
            "Inbox",
            "Root/Inbox",
            (replace(message, index_in_folder=1),),
            index_in_parent=1,
        ),
    )

    message_record = index.get_full_message("archive.pst", database_path, "store:3")

    assert message_record["body"] == "Current source body"
    assert FakeReader.body_calls == [((1,), 1, 3)]


def test_get_full_message_rejects_store_and_body_read_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)

    with pytest.raises(ValueError, match="does not belong"):
        index.get_full_message("archive.pst", database_path, "other:3")

    FakeReader.store_uid = "other"

    with pytest.raises(index.PstSynchronizationError, match="does not match"):
        index.get_full_message("archive.pst", database_path, "store:3")

    FakeReader.store_uid = "store"
    monkeypatch.setattr(
        FakeReader,
        "read_message_body",
        lambda *_: (_ for _ in ()).throw(PstReaderError("body unavailable")),
    )
    with pytest.raises(PstReaderError, match="body unavailable"):
        index.get_full_message("archive.pst", database_path, "store:3")


def test_get_full_message_rejects_a_source_changed_after_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    states = iter(
        (
            index._SourceState("archive.pst", 1, 1),
            index._SourceState("archive.pst", 2, 2),
        )
    )
    monkeypatch.setattr(index, "_source_state", lambda _: next(states))

    with pytest.raises(index.PstSynchronizationError, match="changed during"):
        index.get_full_message("archive.pst", database_path, "store:3")


def test_get_full_message_fails_when_the_source_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    monkeypatch.setattr(
        index,
        "_source_state",
        lambda _: (_ for _ in ()).throw(OSError("source unavailable")),
    )

    with pytest.raises(OSError, match="source unavailable"):
        index.get_full_message("archive.pst", database_path, "store:3")


def test_import_preserves_byte_body_and_indexes_decoded_cleaned_body(
    tmp_path: Path,
) -> None:
    body = b"Current content.\n-----Original Message-----\nQuoted content."
    FakeReader.folders = _records(_message(plain_text_body=body))
    database_path = tmp_path / "index.sqlite"

    index.import_pst("archive.pst", database_path)

    rows = _rows(database_path, "SELECT body_clean, body_format FROM message")
    assert rows == [("Current content.\n", "plain")]
    assert index.search_messages(database_path, "Current")
    assert index.search_messages(database_path, "Quoted") == []


def test_import_persists_attachment_metadata_and_extracts_by_stable_id(
    tmp_path: Path,
) -> None:
    attachment = PstAttachment(
        index=0,
        filename="anonymous-photo.png",
        mime_type="image/png",
        size=20,
        content_id="<photo@example.test>",
        content_location=None,
        attachment_method=1,
        hidden=True,
        rendering_position=0,
    )
    FakeReader.folders = _records(_message(attachments=(attachment,)))
    database_path = tmp_path / "index.sqlite"
    output_path = tmp_path / "photo.png"

    index.import_pst("archive.pst", database_path)

    assert index.list_attachments(database_path, "store:3") == [
        {
            "attachment_method": 1,
            "content_id": "<photo@example.test>",
            "content_location": None,
            "filename": "anonymous-photo.png",
            "hidden": True,
            "id": "store:3:0",
            "mime_type": "image/png",
            "rendering_position": 0,
            "size": 20,
        }
    ]
    assert index.extract_attachment(
        "archive.pst", database_path, "store:3:0", output_path
    ) == len(b"anonymous attachment")
    assert output_path.read_bytes() == b"anonymous attachment"
    assert FakeReader.attachment_calls == [((0,), 0, 3, 0, output_path)]


def test_attachment_extraction_synchronizes_reordered_locators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    attachment = PstAttachment(
        0, "anonymous.png", None, 1, None, None, None, None, None
    )
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    output_path = tmp_path / "anonymous.png"
    message = _message(attachments=(attachment,))
    FakeReader.folders = _records(message)

    index.import_pst("archive.pst", database_path)

    source[0] = index._SourceState("archive.pst", 2, 2)
    FakeReader.folders = (
        PstFolder(1, None, "Root", "Root", ()),
        PstFolder(
            2,
            1,
            "Inbox",
            "Root/Inbox",
            (replace(message, index_in_folder=1),),
            index_in_parent=1,
        ),
    )

    index.extract_attachment("archive.pst", database_path, "store:3:0", output_path)

    assert FakeReader.attachment_calls == [((1,), 1, 3, 0, output_path)]


def test_message_locator_rejects_invalid_cached_values(tmp_path: Path) -> None:
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)

    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE message SET index_in_folder = -1")
        with pytest.raises(ValueError, match="No usable locator"):
            index._message_locator(connection, "store", 3)

        connection.execute("UPDATE message SET index_in_folder = 0")
        connection.execute("UPDATE folder SET parent_nid = 2 WHERE nid = 2")
        with pytest.raises(ValueError, match="Invalid folder ancestry"):
            index._message_locator(connection, "store", 3)

        connection.execute("UPDATE folder SET parent_nid = 1 WHERE nid = 2")
        connection.execute("UPDATE folder SET index_in_parent = 0 WHERE nid = 1")
        with pytest.raises(ValueError, match="Invalid folder ancestry"):
            index._message_locator(connection, "store", 3)

        connection.execute("UPDATE folder SET index_in_parent = -1 WHERE nid = 2")
        connection.execute("UPDATE folder SET index_in_parent = NULL WHERE nid = 1")
        with pytest.raises(ValueError, match="Invalid folder ancestry"):
            index._message_locator(connection, "store", 3)

        connection.execute("DELETE FROM folder WHERE nid = 2")
        with pytest.raises(ValueError, match="Invalid folder ancestry"):
            index._message_locator(connection, "store", 3)


def test_attachment_helpers_reject_invalid_or_missing_identifiers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)

    with pytest.raises(ValueError, match="Invalid attachment"):
        index.extract_attachment(
            "archive.pst", database_path, "store:3", tmp_path / "x"
        )
    with pytest.raises(ValueError, match="Invalid attachment"):
        index.extract_attachment("archive.pst", database_path, "broken", tmp_path / "x")
    with pytest.raises(ValueError, match="Invalid attachment"):
        index.extract_attachment(
            "archive.pst", database_path, "store:3:nope", tmp_path / "x"
        )
    with pytest.raises(ValueError, match="Invalid attachment"):
        index.extract_attachment(
            "archive.pst", database_path, "store:3:-1", tmp_path / "x"
        )
    with pytest.raises(ValueError, match="Attachment not found"):
        index.extract_attachment(
            "archive.pst", database_path, "store:3:9", tmp_path / "x"
        )
    with pytest.raises(ValueError, match="does not belong"):
        index.list_attachments(database_path, "other:3")
    monkeypatch.setattr(
        index,
        "_require_index_state",
        lambda _: index._IndexState(
            index._SourceState("archive.pst", 1, 1), "other", 4, 1, 1
        ),
    )
    with pytest.raises(ValueError, match="does not belong"):
        index.extract_attachment(
            "archive.pst", database_path, "store:3:0", tmp_path / "x"
        )


def test_attachment_extraction_rejects_a_replacement_store(tmp_path: Path) -> None:
    attachment = PstAttachment(0, None, None, 1, None, None, None, None, None)
    FakeReader.folders = _records(_message(attachments=(attachment,)))
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    FakeReader.store_uid = "replacement"

    with pytest.raises(index.PstSynchronizationError, match="does not match"):
        index.extract_attachment(
            "archive.pst", database_path, "store:3:0", tmp_path / "x"
        )


def test_import_pst_replaces_the_cache_only_after_a_successful_import(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    FakeReader.error = OSError("broken traversal")

    with pytest.raises(OSError, match="broken traversal"):
        index.import_pst("archive.pst", database_path)

    assert _rows(database_path, "SELECT nid FROM message") == [(3,)]
    assert list(tmp_path.glob(".index.sqlite.*.tmp")) == []


def test_import_pst_rebuilds_an_equivalent_deleted_cache(tmp_path: Path) -> None:
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    expected = _rows(database_path, "SELECT nid, body_clean FROM message")
    database_path.unlink()

    index.import_pst("archive.pst", database_path)

    assert _rows(database_path, "SELECT nid, body_clean FROM message") == expected


def test_import_pst_preserves_an_existing_cache_when_replacement_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)

    def fail_replace(_: Path, __: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(index.os, "replace", fail_replace)

    with pytest.raises(OSError, match="disk full"):
        index.import_pst("archive.pst", database_path)

    assert _rows(database_path, "SELECT nid FROM message") == [(3,)]


def test_relationship_parser_handles_missing_headers() -> None:
    assert index._relationships(None) == {
        "internet_message_id": None,
        "in_reply_to": None,
        "references_header": None,
        "conversation_topic": None,
        "conversation_index": None,
    }


def test_sync_pst_skips_traversal_when_source_metadata_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    FakeReader.walk_arguments = []

    result = index.sync_pst("archive.pst", database_path)

    assert result.skipped is True
    assert result.full is False
    assert FakeReader.walk_arguments == []


def test_sync_pst_rebuilds_when_the_cleaner_version_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    FakeReader.walk_arguments = []
    monkeypatch.setattr(index, "CLEANER_VERSION", index.CLEANER_VERSION + 1)

    result = index.sync_pst("archive.pst", database_path)

    assert result.full is True
    assert FakeReader.walk_arguments == [
        {"include_bodies": True, "include_body_nids": None}
    ]
    assert _rows(database_path, "SELECT cleaner_version FROM index_state") == [
        (index.CLEANER_VERSION,)
    ]


def test_sync_pst_rebuilds_when_the_schema_version_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("UPDATE index_state SET schema_version = ?", (11,))
    FakeReader.walk_arguments = []

    result = index.sync_pst("archive.pst", database_path)

    assert result.full is True
    assert FakeReader.walk_arguments == [
        {"include_bodies": True, "include_body_nids": None}
    ]
    assert "body_raw" not in {
        row[1] for row in _rows(database_path, "PRAGMA table_info(message)")
    }


def test_sync_pst_rebuilds_derived_history_when_owner_context_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    FakeReader.folders = _records(
        _message(
            plain_text_body=(
                "Current\nFrom: Owner <owner@example.test>\n"
                "Sent: 20.08.2026 10:00\nTo: Recipient\nSubject: Status\nRecovered"
            )
        )
    )
    owner_history = index.HistorySettings(("owner@example.test",), (), "UTC")
    index.import_pst("archive.pst", database_path, owner_history)
    FakeReader.walk_arguments = []

    result = index.sync_pst("archive.pst", database_path, index.HistorySettings())

    assert result.full is True
    assert _rows(database_path, "SELECT * FROM recovered_message") == []
    assert index.search_messages(database_path, "Recovered") == []
    assert _rows(
        database_path,
        "SELECT COUNT(*) FROM search_document WHERE recovered_fingerprint IS NOT NULL",
    ) == [(0,)]
    assert FakeReader.walk_arguments == [
        {"include_bodies": True, "include_body_nids": None}
    ]


def test_sync_pst_reloads_only_new_and_modified_message_bodies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    changed = _message(
        plain_text_body="Changed body",
        modification_time=datetime(2026, 8, 21, 12, 30),
    )
    new = replace(_message(nid=4, plain_text_body="New body"), folder_nid=2)
    FakeReader.folders = _records(changed, new)
    FakeReader.walk_arguments = []
    source[0] = index._SourceState("archive.pst", 2, 2)

    result = index.sync_pst("archive.pst", database_path)

    assert (result.new_count, result.modified_count) == (1, 1)
    assert FakeReader.walk_arguments == [
        {"include_bodies": False, "include_body_nids": None},
        {"include_bodies": False, "include_body_nids": {3, 4}},
    ]
    assert _rows(database_path, "SELECT nid, body_clean FROM message ORDER BY nid") == [
        (3, "Changed body"),
        (4, "New body"),
    ]


def test_sync_pst_updates_only_folder_for_same_nid_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    moved = replace(_message(), folder_nid=4)
    FakeReader.folders = (
        PstFolder(1, None, "Root", "Root", ()),
        PstFolder(2, 1, "Inbox", "Root/Inbox", ()),
        PstFolder(4, 1, "Archive", "Root/Archive", (moved,)),
    )
    FakeReader.walk_arguments = []
    source[0] = index._SourceState("archive.pst", 2, 2)

    result = index.sync_pst("archive.pst", database_path)

    assert result.moved_count == 1
    assert FakeReader.walk_arguments == [
        {"include_bodies": False, "include_body_nids": None}
    ]
    assert _rows(database_path, "SELECT folder_nid, body_clean FROM message") == [
        (4, "Plain body")
    ]


def test_sync_pst_removes_messages_not_seen_in_successful_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    FakeReader.folders = _records()
    source[0] = index._SourceState("archive.pst", 2, 2)

    result = index.sync_pst("archive.pst", database_path)

    assert result.deleted_count == 1
    assert _rows(database_path, "SELECT nid FROM message") == []


def test_sync_pst_preserves_cache_when_traversal_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    before = database_path.read_bytes()
    FakeReader.error = OSError("broken traversal")
    source[0] = index._SourceState("archive.pst", 2, 2)

    with pytest.raises(OSError, match="broken traversal"):
        index.sync_pst("archive.pst", database_path)

    assert database_path.read_bytes() == before
    assert list(tmp_path.glob(".index.sqlite.*.tmp")) == []


def test_sync_pst_preserves_cache_when_source_changes_during_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    states = iter(
        (
            index._SourceState("archive.pst", 1, 1),
            index._SourceState("archive.pst", 1, 1),
            index._SourceState("archive.pst", 2, 2),
            index._SourceState("archive.pst", 3, 3),
        )
    )
    monkeypatch.setattr(index, "_source_state", lambda _: next(states))
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    before = database_path.read_bytes()

    with pytest.raises(index.PstSynchronizationError, match="changed"):
        index.sync_pst("archive.pst", database_path)

    assert database_path.read_bytes() == before


def test_sync_pst_full_rebuild_is_available_for_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    FakeReader.walk_arguments = []

    result = index.sync_pst("archive.pst", database_path, full=True)

    assert result.full is True
    assert FakeReader.walk_arguments == [
        {"include_bodies": True, "include_body_nids": None}
    ]


def test_sync_pst_rebuilds_a_cache_without_current_index_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    with sqlite3.connect(database_path):
        pass

    result = index.sync_pst("archive.pst", database_path)

    assert result.full is True
    with sqlite3.connect(tmp_path / "empty.sqlite") as connection:
        index._create_schema(connection)
    assert index._read_index_state(tmp_path / "empty.sqlite") is None


def test_sync_pst_rebuilds_when_the_pst_store_identity_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    source[0] = index._SourceState("archive.pst", 2, 2)
    FakeReader.store_uid = "replacement"

    result = index.sync_pst("archive.pst", database_path)

    assert result.full is True
    assert result.store_uid == "replacement"


def test_sync_pst_rejects_a_store_change_between_metadata_and_body_scans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    source[0] = index._SourceState("archive.pst", 2, 2)
    FakeReader.folders = _records(
        _message(modification_time=datetime(2026, 8, 21, 12, 30))
    )
    original_init = FakeReader.__init__
    calls = 0

    def init_with_changed_second_store(self: FakeReader, path: str | Path) -> None:
        nonlocal calls
        original_init(self, path)
        calls += 1
        if calls == 2:
            self.store = PstStore("replacement")

    monkeypatch.setattr(FakeReader, "__init__", init_with_changed_second_store)

    with pytest.raises(index.PstSynchronizationError, match="store changed"):
        index.sync_pst("archive.pst", database_path)


def test_sync_pst_rejects_messages_missing_from_the_body_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    source[0] = index._SourceState("archive.pst", 2, 2)
    original_init = FakeReader.__init__
    calls = 0

    def init_with_missing_second_message(self: FakeReader, path: str | Path) -> None:
        nonlocal calls
        original_init(self, path)
        calls += 1
        self.folders = (
            _records(_message(modification_time=datetime(2026, 8, 21, 12, 30)))
            if calls == 1
            else _records()
        )

    monkeypatch.setattr(FakeReader, "__init__", init_with_missing_second_message)

    with pytest.raises(index.PstSynchronizationError, match="messages changed"):
        index.sync_pst("archive.pst", database_path)


def test_source_state_records_resolved_path_and_stat_metadata(tmp_path: Path) -> None:
    source = tmp_path / "archive.pst"
    source.write_bytes(b"pst")

    state = REAL_SOURCE_STATE(source)

    assert state.path == str(source.resolve())
    assert state.size == 3
    assert state.mtime_ns == source.stat().st_mtime_ns


def test_index_queries_searchable_messages_and_persisted_records(
    tmp_path: Path,
) -> None:
    message = replace(
        _message(plain_text_body="Capon calibration is ready."),
        transport_headers=(
            "Message-ID: <message@example.test>\n"
            "To: Recipient <recipient@example.test>\n"
            "Cc: Copy <copy@example.test>\n"
        ),
    )
    FakeReader.folders = _records(message)
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)

    results = index.search_messages(
        database_path,
        "Capon",
        sender="sender",
        recipient="recipient@example.test",
        after="2026-08-20T00:00:00",
        before="2026-08-21T00:00:00",
        folder="Root/Inbox",
        has_attachment=True,
        limit=1,
    )

    assert results[0].as_dict() == {
        "date": "2026-08-20T12:30:00",
        "folder": "Root/Inbox",
        "from": "Sender",
        "id": "store:3",
        "score": results[0].score,
        "snippet": "Capon calibration is ready.",
        "subject": "Status update",
        "to": ["recipient@example.test", "copy@example.test"],
    }
    assert results[0].score > 0
    assert index.search_messages(database_path, "Recipient")
    assert index.list_folders(database_path) == [
        {"id": "store:1", "name": "Root", "parent_id": None, "path": "Root"},
        {
            "id": "store:2",
            "name": "Inbox",
            "parent_id": "store:1",
            "path": "Root/Inbox",
        },
    ]
    assert index.get_message(database_path, "store:3")["body"] == (
        "Capon calibration is ready."
    )
    assert index.get_message(database_path, "store:3")["to"] == [
        "recipient@example.test",
        "copy@example.test",
    ]


def test_search_rejects_invalid_fts_syntax(tmp_path: Path) -> None:
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)

    with pytest.raises(ValueError, match="Invalid FTS query"):
        index.search_messages(database_path, '"')


def test_search_replaces_invalid_utf8_in_fts_snippets(tmp_path: Path) -> None:
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    with sqlite3.connect(database_path) as connection:
        rowid = connection.execute(
            "SELECT rowid FROM search_document WHERE store_uid = ? AND native_nid = ?",
            ("store", 3),
        ).fetchone()[0]
        connection.execute("DELETE FROM search_fts WHERE rowid = ?", (rowid,))
        connection.execute(
            """
            INSERT INTO search_fts (rowid, subject, sender, recipients, body)
            VALUES (?, '', '', '', CAST(X'63686f636f6c61746520ff' AS TEXT))
            """,
            (rowid,),
        )

    results = index.search_messages(database_path, "chocolate")

    assert results[0].snippet == "chocolate \ufffd"


def test_get_message_decodes_byte_valued_fields_for_json(tmp_path: Path) -> None:
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE message SET body_clean = ? WHERE store_uid = ? AND nid = ?",
            (b"Body with invalid byte: \xff", "store", 3),
        )
        connection.execute(
            """
            INSERT INTO recipient (
                store_uid, message_nid, recipient_index, recipient_type, name, email
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("store", 3, 0, "to", None, b"recipient\xff@example.test"),
        )

    message = index.get_message(database_path, "store:3")

    assert message["body"] == "Body with invalid byte: \ufffd"
    assert message["to"] == ["recipient\ufffd@example.test"]
    json.dumps(message)


def test_index_status_reports_freshness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = [index._SourceState("archive.pst", 1, 1)]
    monkeypatch.setattr(index, "_source_state", lambda _: source[0])
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)

    assert index.index_status("archive.pst", database_path)["fresh"] is True
    source[0] = index._SourceState("archive.pst", 2, 2)

    assert index.index_status("archive.pst", database_path)["fresh"] is False


def test_index_status_reports_unavailable_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        index,
        "_source_state",
        lambda _: (_ for _ in ()).throw(OSError("unavailable")),
    )

    report = index.index_status("archive.pst", tmp_path / "missing.sqlite")

    assert report["fresh"] is False
    assert report["source_error"] == "unavailable"


def test_query_helpers_reject_missing_or_invalid_records(tmp_path: Path) -> None:
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)

    with pytest.raises(ValueError, match="must not be empty"):
        index.search_messages(database_path, " ")
    with pytest.raises(ValueError, match="does not belong"):
        index.get_message(database_path, "other:3")
    with pytest.raises(ValueError, match="Message not found"):
        index.get_message(database_path, "store:99")
    with pytest.raises(ValueError, match="No current"):
        index.list_folders(tmp_path / "missing.sqlite")
    with pytest.raises(ValueError, match="Invalid message ID"):
        index.get_message(database_path, "invalid")
    with pytest.raises(ValueError, match="Invalid message ID"):
        index.get_message(database_path, "store:not-a-number")
    with pytest.raises(ValueError, match="does not belong"):
        index.get_message(database_path, "other:q:fingerprint")
    with pytest.raises(ValueError, match="Message not found"):
        index.get_message(database_path, "store:q:fingerprint")
    with pytest.raises(ValueError, match="Message not found"):
        index.get_thread(database_path, "store:q:fingerprint")
    with pytest.raises(ValueError, match="does not belong"):
        index.list_attachments(database_path, "other:q:fingerprint")


def test_recipient_and_fts_helpers_handle_empty_records(tmp_path: Path) -> None:
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)

    with sqlite3.connect(database_path) as connection:
        index._replace_recipients(connection, "store", 3, None)
        index._index_message(connection, "store", 99)

        assert index._recipients_for_messages(connection, "store", []) == {}


def test_search_propagates_non_fts_database_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "index.sqlite"
    index.import_pst("archive.pst", database_path)
    real_connect = index.sqlite3.connect
    calls = 0

    def connect_with_failed_query(path: Path) -> sqlite3.Connection:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_connect(path)
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(index.sqlite3, "connect", connect_with_failed_query)

    with pytest.raises(sqlite3.OperationalError, match="locked"):
        index.search_messages(database_path, "Plain")
