"""Tests for the disposable SQLite full-import cache."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from pstq import index
from pstq.pst import PstFolder, PstMessage, PstStore


def _message(
    *,
    nid: int = 3,
    folder_nid: int = 2,
    plain_text_body: str | None = "Plain body",
    html_body: str | None = "<p>HTML body</p>",
    rtf_body: str | None = "RTF body",
) -> PstMessage:
    return PstMessage(
        nid=nid,
        folder_nid=folder_nid,
        modification_time=datetime(2026, 8, 20, 12, 30),
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
    walk_arguments: list[dict[str, object]] = []

    def __init__(self, _: str | Path) -> None:
        self.store = PstStore("store")

    def __enter__(self) -> FakeReader:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def walk(self, *, include_bodies: bool = False):
        self.walk_arguments.append({"include_bodies": include_bodies})
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
    FakeReader.walk_arguments = []
    FakeReader.folders = _records(_message())
    monkeypatch.setattr(index, "PstReader", FakeReader)


def _rows(path: Path, statement: str) -> list[tuple[object, ...]]:
    with sqlite3.connect(path) as connection:
        return connection.execute(statement).fetchall()


def test_import_pst_creates_normalized_cache(tmp_path: Path) -> None:
    database_path = tmp_path / "index.sqlite"

    result = index.import_pst("archive.pst", database_path)

    assert result == index.ImportResult("store", folder_count=2, message_count=1)
    assert FakeReader.walk_arguments == [{"include_bodies": True}]
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
    expected = database_path.read_bytes()
    database_path.unlink()

    index.import_pst("archive.pst", database_path)

    assert database_path.read_bytes() == expected


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
