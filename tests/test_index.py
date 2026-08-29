"""Tests for the disposable SQLite full-import cache."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest

from pstq import index
from pstq.pst import PstFolder, PstMessage, PstStore

REAL_SOURCE_STATE = index._source_state


def _message(
    *,
    nid: int = 3,
    folder_nid: int = 2,
    plain_text_body: str | None = "Plain body",
    html_body: str | None = "<p>HTML body</p>",
    rtf_body: str | None = "RTF body",
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
    )


class FakeReader:
    folders: tuple[PstFolder, ...] = ()
    error: Exception | None = None
    store_uid = "store"
    walk_arguments: list[dict[str, object]] = []

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
        ),
    )


@pytest.fixture(autouse=True)
def fake_reader(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeReader.error = None
    FakeReader.store_uid = "store"
    FakeReader.walk_arguments = []
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
        "SELECT store_uid, nid, parent_nid, name, path FROM folder ORDER BY nid",
    ) == [
        ("store", 1, None, "Root", "Root"),
        ("store", 2, 1, "Inbox", "Root/Inbox"),
    ]
    assert _rows(
        database_path,
        """
        SELECT nid, folder_nid, modification_time, subject, sender_name,
               client_submit_time, delivery_time, body_raw, body_format,
               internet_message_id, in_reply_to, references_header,
               conversation_topic, conversation_index, attachment_count
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


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (_message(plain_text_body=None), ("<p>HTML body</p>", "html")),
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

    assert _rows(database_path, "SELECT body_raw, body_format FROM message") == [
        expected
    ]


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
    expected = _rows(database_path, "SELECT nid, body_raw FROM message")
    database_path.unlink()

    index.import_pst("archive.pst", database_path)

    assert _rows(database_path, "SELECT nid, body_raw FROM message") == expected


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
    assert _rows(database_path, "SELECT nid, body_raw FROM message ORDER BY nid") == [
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
    assert _rows(database_path, "SELECT folder_nid, body_raw FROM message") == [
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
            "SELECT rowid FROM message WHERE store_uid = ? AND nid = ?", ("store", 3)
        ).fetchone()[0]
        connection.execute("DELETE FROM message_fts WHERE rowid = ?", (rowid,))
        connection.execute(
            """
            INSERT INTO message_fts (rowid, subject, sender, recipients, body)
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
            "UPDATE message SET body_raw = ? WHERE store_uid = ? AND nid = ?",
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
