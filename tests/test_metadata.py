"""Tests for metadata-only inspection and durable snapshots."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from pstq import metadata
from pstq.metadata import (
    FolderMetadata,
    MessageMetadata,
    MetadataSnapshot,
    SnapshotFormatError,
    compare_snapshots,
    inspect_pst,
    read_snapshot,
    write_snapshot,
)
from pstq.pst import PstFolder, PstMessage, PstStore


class FakeReader:
    walk_arguments: list[dict[str, object]] = []
    walk_error: Exception | None = None

    def __init__(self, path: Path) -> None:
        self.path = path
        self.store = PstStore("store")

    def __enter__(self) -> FakeReader:
        return self

    def __exit__(self, *_: object) -> None:
        pass

    def walk(self):
        self.walk_arguments.append({})
        yield PstFolder(
            nid=2,
            parent_nid=None,
            name="Inbox",
            path="Inbox",
            messages=(
                PstMessage(
                    nid=4,
                    folder_nid=2,
                    modification_time=datetime(2026, 8, 20, 12, 30),
                    subject="Second",
                    sender_name=None,
                    client_submit_time=None,
                    delivery_time=None,
                    transport_headers=None,
                    conversation_topic=None,
                    conversation_index=None,
                    attachment_count=0,
                    plain_text_body=None,
                    rtf_body=None,
                    html_body=None,
                ),
                PstMessage(
                    nid=3,
                    folder_nid=2,
                    modification_time=None,
                    subject="First",
                    sender_name=None,
                    client_submit_time=None,
                    delivery_time=None,
                    transport_headers=None,
                    conversation_topic=None,
                    conversation_index=None,
                    attachment_count=0,
                    plain_text_body=None,
                    rtf_body=None,
                    html_body=None,
                ),
            ),
        )
        if self.walk_error is not None:
            raise self.walk_error


def _snapshot(*messages: MessageMetadata, store_uid: str = "store") -> MetadataSnapshot:
    return MetadataSnapshot(
        store_uid=store_uid,
        folders=(FolderMetadata(nid=2, path="Inbox"),),
        messages=messages,
    )


def test_inspect_collects_only_metadata_and_bounded_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "archive.pst"
    path.write_bytes(b"1234")
    FakeReader.walk_arguments = []
    FakeReader.walk_error = None
    monkeypatch.setattr(metadata, "PstReader", FakeReader)
    monkeypatch.setattr(metadata, "_libpff_version", lambda: "20231205")

    inspection = inspect_pst(path, sample_size=1)

    assert FakeReader.walk_arguments == [{}]
    assert inspection.libpff_version == "20231205"
    assert inspection.pst_size == 4
    assert inspection.folder_count == 1
    assert inspection.message_count == 2
    assert inspection.messages_per_second is not None
    assert inspection.scan_errors == ()
    assert inspection.as_dict()["message_count"] == 2
    assert inspection.samples == (
        {
            "folder_nid": 2,
            "folder_path": "Inbox",
            "modification_time": "2026-08-20T12:30:00",
            "nid": 4,
            "subject": "Second",
        },
    )
    assert [message.nid for message in inspection.snapshot.messages] == [3, 4]


def test_inspect_reports_a_partial_scan_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "archive.pst"
    path.touch()
    FakeReader.walk_error = OSError("bad item")
    monkeypatch.setattr(metadata, "PstReader", FakeReader)

    inspection = inspect_pst(path)

    assert inspection.message_count == 2
    assert inspection.scan_errors == ("OSError: bad item",)
    FakeReader.walk_error = None


def test_inspect_rejects_a_negative_sample_size(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        inspect_pst(tmp_path / "archive.pst", sample_size=-1)


def test_snapshot_json_is_stable_and_round_trips(tmp_path: Path) -> None:
    snapshot = MetadataSnapshot(
        store_uid="store",
        folders=(
            FolderMetadata(nid=3, path="Z"),
            FolderMetadata(nid=2, path="A"),
        ),
        messages=(
            MessageMetadata(nid=4, folder_nid=2, modification_time=None),
            MessageMetadata(
                nid=3, folder_nid=2, modification_time="2026-08-20T12:30:00"
            ),
        ),
    )
    path = tmp_path / "snapshot.json"

    write_snapshot(snapshot, path)

    assert path.read_text() == (
        "{\n"
        '  "folders": [\n'
        "    {\n"
        '      "nid": 3,\n'
        '      "path": "Z"\n'
        "    },\n"
        "    {\n"
        '      "nid": 2,\n'
        '      "path": "A"\n'
        "    }\n"
        "  ],\n"
        '  "format_version": 1,\n'
        '  "messages": [\n'
        "    {\n"
        '      "folder_nid": 2,\n'
        '      "modification_time": null,\n'
        '      "nid": 4\n'
        "    },\n"
        "    {\n"
        '      "folder_nid": 2,\n'
        '      "modification_time": "2026-08-20T12:30:00",\n'
        '      "nid": 3\n'
        "    }\n"
        "  ],\n"
        '  "store_uid": "store"\n'
        "}\n"
    )
    assert read_snapshot(path) == snapshot


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not json", "Unable to read"),
        ("[]", "root must be an object"),
        ("{}", "Unsupported snapshot format version"),
        (
            '{"format_version": 1, "store_uid": 1, "folders": [], "messages": []}',
            "store_uid",
        ),
        (
            '{"format_version": 1, "store_uid": "x", "folders": {}, "messages": []}',
            "arrays",
        ),
        (
            '{"format_version": 1, "store_uid": "x", "folders": [1], "messages": []}',
            "folder",
        ),
        (
            '{"format_version": 1, "store_uid": "x", "folders": [], "messages": [1]}',
            "message",
        ),
    ],
)
def test_read_snapshot_rejects_invalid_content(
    tmp_path: Path, content: str, message: str
) -> None:
    path = tmp_path / "snapshot.json"
    path.write_text(content)

    with pytest.raises(SnapshotFormatError, match=message):
        read_snapshot(path)


def test_read_snapshot_rejects_invalid_message_and_folder_fields(
    tmp_path: Path,
) -> None:
    path = tmp_path / "snapshot.json"
    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "store_uid": "x",
                "folders": [{"nid": "bad", "path": 1}],
                "messages": [],
            }
        )
    )
    with pytest.raises(SnapshotFormatError, match="integer nid"):
        read_snapshot(path)

    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "store_uid": "x",
                "folders": [],
                "messages": [{"nid": 1, "folder_nid": "bad", "modification_time": 1}],
            }
        )
    )
    with pytest.raises(SnapshotFormatError, match="folder_nid"):
        read_snapshot(path)

    path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "store_uid": "x",
                "folders": [],
                "messages": [{"nid": 1, "folder_nid": 2, "modification_time": 1}],
            }
        )
    )
    with pytest.raises(SnapshotFormatError, match="modification_time"):
        read_snapshot(path)


def test_compare_snapshots_classifies_all_changes_and_identity_warnings() -> None:
    before = _snapshot(
        MessageMetadata(nid=1, folder_nid=2, modification_time="one"),
        MessageMetadata(nid=2, folder_nid=2, modification_time="two"),
        MessageMetadata(nid=3, folder_nid=2, modification_time="three"),
        MessageMetadata(nid=4, folder_nid=9, modification_time=None),
        MessageMetadata(nid=5, folder_nid=2, modification_time=None),
        MessageMetadata(nid=5, folder_nid=2, modification_time=None),
    )
    after = _snapshot(
        MessageMetadata(nid=1, folder_nid=2, modification_time="updated"),
        MessageMetadata(nid=2, folder_nid=3, modification_time="two"),
        MessageMetadata(nid=3, folder_nid=2, modification_time="three"),
        MessageMetadata(nid=6, folder_nid=2, modification_time=None),
        store_uid="other",
    )

    comparison = compare_snapshots(before, after)

    assert comparison["new"] == [{"folder_nid": 2, "modification_time": None, "nid": 6}]
    assert comparison["missing"] == [
        {"folder_nid": 9, "modification_time": None, "nid": 4}
    ]
    assert comparison["modified"] == [
        {
            "after_modification_time": "updated",
            "before_modification_time": "one",
            "nid": 1,
        }
    ]
    assert comparison["moved"] == [
        {"after_folder_nid": 3, "before_folder_nid": 2, "nid": 2}
    ]
    assert comparison["unchanged"] == {"count": 1}
    assert comparison["suspicious_identity"] == {
        "after": {
            "duplicate_folder_nids": [],
            "duplicate_message_nids": [],
            "messages_with_unknown_folder_nids": [2],
        },
        "before": {
            "duplicate_folder_nids": [],
            "duplicate_message_nids": [5],
            "messages_with_unknown_folder_nids": [4],
        },
        "store_uid_changed": True,
    }


def test_compare_reports_duplicate_folder_nids() -> None:
    snapshot = MetadataSnapshot(
        store_uid="store",
        folders=(FolderMetadata(nid=2, path="A"), FolderMetadata(nid=2, path="B")),
        messages=(),
    )

    comparison = compare_snapshots(snapshot, snapshot)

    assert comparison["suspicious_identity"]["before"]["duplicate_folder_nids"] == [2]


def test_libpff_version_is_unknown_when_import_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_import_error(_: str) -> object:
        raise ImportError("missing")

    monkeypatch.setattr(metadata, "import_module", raise_import_error)

    assert metadata._libpff_version() == "unknown"


def test_libpff_version_handles_callable_and_missing_version_apis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PypffWithVersion:
        @staticmethod
        def get_version() -> str:
            return "20231205"

    class PypffWithoutCallableVersion:
        get_version = "not callable"

    monkeypatch.setattr(metadata, "import_module", lambda _: PypffWithVersion)
    assert metadata._libpff_version() == "20231205"

    monkeypatch.setattr(
        metadata, "import_module", lambda _: PypffWithoutCallableVersion
    )
    assert metadata._libpff_version() == "unknown"
