"""Tests for the read-only pypff adapter."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from pstq import pst
from pstq.pst import (
    PID_TAG_CONVERSATION_INDEX,
    PID_TAG_CONVERSATION_TOPIC,
    PID_TAG_IN_REPLY_TO_ID,
    PID_TAG_INTERNET_MESSAGE_ID,
    PID_TAG_INTERNET_REFERENCES,
    PID_TAG_RECORD_KEY,
    PstFileNotFoundError,
    PstFileUnreadableError,
    PstReader,
    PstStoreIdentityError,
)


class FakeRecordEntry:
    def __init__(self, data: object) -> None:
        self.data = data


class FakeRecordSet:
    def __init__(self, record_key: object | None) -> None:
        self.record_key = record_key

    def get_entry_by_type(self, entry_type: int) -> FakeRecordEntry | None:
        if entry_type == PID_TAG_RECORD_KEY and self.record_key is not None:
            return FakeRecordEntry(self.record_key)
        return None


class LegacyFakeRecordSet:
    def __init__(self, record_key: bytes) -> None:
        self.entries = [FakeRecordEntry(record_key)]
        self.entries[0].entry_type = PID_TAG_RECORD_KEY


class FakeMessageStore:
    def __init__(self, record_key: object | None) -> None:
        self.record_sets = [FakeRecordSet(record_key)]


class FakeMessage:
    identifier = 200
    modification_time = datetime(2026, 8, 20, 12, 30)
    subject = "Status update"
    sender_name = "Sender"
    client_submit_time = datetime(2026, 8, 20, 12, 0)
    delivery_time = datetime(2026, 8, 20, 12, 30)
    transport_headers = "Message-ID: <message@example.test>"
    conversation_topic = "Status"
    conversation_index = bytes.fromhex("010203")
    number_of_attachments = 1
    plain_text_body = "Plain body"
    rtf_body = "RTF body"
    html_body = "<p>HTML body</p>"


class FakeMessageEntry:
    def __init__(self, entry_type: int, data: object, text: object) -> None:
        self.entry_type = entry_type
        self.data = data
        self.data_as_string = text


class FakeMessageRecordSet:
    def __init__(self, entries: list[FakeMessageEntry]) -> None:
        self.entries = entries


class LookupMessageRecordSet:
    def __init__(self, entry: FakeMessageEntry) -> None:
        self.entry = entry

    def get_entry_by_type(self, entry_type: int) -> FakeMessageEntry | None:
        return self.entry if entry_type == self.entry.entry_type else None


class MapiFakeMessage(FakeMessage):
    conversation_topic = "Direct topic"
    conversation_index = bytes.fromhex("010203")
    record_sets = [
        FakeMessageRecordSet(
            [
                FakeMessageEntry(PID_TAG_CONVERSATION_TOPIC, b"", "MAPI topic"),
                FakeMessageEntry(PID_TAG_CONVERSATION_INDEX, bytes.fromhex("AABB"), ""),
                FakeMessageEntry(
                    PID_TAG_INTERNET_MESSAGE_ID, b"", "<mapi@example.test>"
                ),
                FakeMessageEntry(PID_TAG_IN_REPLY_TO_ID, b"", "<parent@example.test>"),
                FakeMessageEntry(
                    PID_TAG_INTERNET_REFERENCES,
                    b"",
                    "<root@example.test> <parent@example.test>",
                ),
            ]
        )
    ]


class SparseFakeMessage(FakeMessage):
    @property
    def conversation_index(self) -> bytes:
        raise OSError("missing property")


class FakeAttachmentEntry:
    def __init__(self, entry_type: int, value: object) -> None:
        self.entry_type = entry_type
        self.data_as_string = value
        self.data_as_integer = value
        self.data_as_boolean = value


class FakeAttachmentRecordSet:
    def __init__(self, entries: list[FakeAttachmentEntry]) -> None:
        self.entries = entries


class FakeAttachment:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.size = len(data)
        self.offset = 0
        self.record_sets = [
            FakeAttachmentRecordSet(
                [
                    FakeAttachmentEntry(0x3707, "anonymous-image.png"),
                    FakeAttachmentEntry(0x370E, "image/png"),
                    FakeAttachmentEntry(0x3712, "<image@example.test>"),
                    FakeAttachmentEntry(0x3705, 1),
                    FakeAttachmentEntry(0x7FFE, True),
                    FakeAttachmentEntry(0x370B, 0),
                ]
            )
        ]

    def read_buffer(self, size: int) -> bytes:
        chunk = self.data[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk


class AttachmentFakeMessage(FakeMessage):
    def __init__(self, attachment: FakeAttachment) -> None:
        self._attachment = attachment

    def get_attachment(self, index: int) -> FakeAttachment:
        if index != 0:
            raise OSError("missing attachment")
        return self._attachment


class FakeFolder:
    def __init__(
        self,
        identifier: int,
        name: str | None,
        messages: list[FakeMessage] | None = None,
        folders: list[FakeFolder] | None = None,
    ) -> None:
        self.identifier = identifier
        self.name = name
        self._messages = messages or []
        self._folders = folders or []

    @property
    def number_of_sub_messages(self) -> int:
        return len(self._messages)

    @property
    def number_of_sub_folders(self) -> int:
        return len(self._folders)

    def get_sub_message(self, index: int) -> FakeMessage:
        return self._messages[index]

    def get_sub_folder(self, index: int) -> FakeFolder:
        return self._folders[index]


class FakePypffFile:
    def __init__(
        self, record_key: object | None, *, open_error: OSError | None = None
    ) -> None:
        self.message_store = FakeMessageStore(record_key)
        self.root_folder = FakeFolder(
            100,
            "Root",
            folders=[FakeFolder(101, "Inbox", messages=[FakeMessage()])],
        )
        self.open_error = open_error
        self.open_arguments: tuple[str, str] | None = None
        self.closed = False

    def open(self, filename: str, mode: str = "r") -> None:
        self.open_arguments = (filename, mode)
        if self.open_error is not None:
            raise self.open_error

    def close(self) -> None:
        self.closed = True


class FakePypff:
    def __init__(self, file: FakePypffFile) -> None:
        self._file = file

    def file(self) -> FakePypffFile:
        return self._file


def test_open_normalizes_record_key_and_walks_messages(tmp_path: Path) -> None:
    path = tmp_path / "archive.pst"
    path.touch()
    pypff_file = FakePypffFile(bytes.fromhex("AABBCC"))

    with PstReader(path, pypff_module=FakePypff(pypff_file)) as reader:
        assert reader.store.uid == "aabbcc"
        folders = list(reader.walk())

    assert pypff_file.open_arguments == (str(path), "r")
    assert pypff_file.closed
    assert [
        (folder.nid, folder.parent_nid, folder.path, folder.index_in_parent)
        for folder in folders
    ] == [
        (100, None, "Root", None),
        (101, 100, "Root/Inbox", 0),
    ]
    message = folders[1].messages[0]
    assert message.nid == 200
    assert message.folder_nid == 101
    assert message.index_in_folder == 0
    assert message.modification_time == datetime(2026, 8, 20, 12, 30)
    assert message.conversation_index == "010203"
    assert message.transport_headers == "Message-ID: <message@example.test>"
    assert message.attachment_count == 1
    assert message.plain_text_body is None


def test_open_prefers_mapi_relationship_properties(tmp_path: Path) -> None:
    path = tmp_path / "archive.pst"
    path.touch()
    pypff_file = FakePypffFile(bytes.fromhex("AABBCC"))
    pypff_file.root_folder._folders[0]._messages = [MapiFakeMessage()]

    with PstReader(path, pypff_module=FakePypff(pypff_file)) as reader:
        message = list(reader.walk())[1].messages[0]

    assert message.conversation_topic == "MAPI topic"
    assert message.conversation_index == "aabb"
    assert message.internet_message_id == "<mapi@example.test>"
    assert message.in_reply_to == "<parent@example.test>"
    assert message.references_header == "<root@example.test> <parent@example.test>"


def test_message_property_helpers_ignore_malformed_entries(tmp_path: Path) -> None:
    class BrokenTextEntry:
        entry_type = 0x9999

        @property
        def data_as_string(self) -> str:
            raise ValueError("broken")

    class BrokenBytesEntry:
        entry_type = PID_TAG_CONVERSATION_INDEX
        data = object()

    class Message:
        conversation_index = object()
        record_sets = [
            LookupMessageRecordSet(
                FakeMessageEntry(PID_TAG_CONVERSATION_TOPIC, b"", "Topic")
            ),
            FakeMessageRecordSet([BrokenTextEntry(), BrokenBytesEntry()]),
        ]

    reader = PstReader(
        tmp_path / "archive.pst", pypff_module=FakePypff(FakePypffFile(b"x"))
    )

    assert reader._message_text(Message(), PID_TAG_CONVERSATION_TOPIC) == "Topic"
    assert reader._message_text(Message(), 0x9999) is None
    assert reader._message_bytes(Message(), PID_TAG_CONVERSATION_INDEX) is None


def test_open_reads_a_record_key_from_legacy_pypff_entries(tmp_path: Path) -> None:
    path = tmp_path / "archive.pst"
    path.touch()
    pypff_file = FakePypffFile(bytes.fromhex("AABBCC"))
    pypff_file.message_store.record_sets = [
        LegacyFakeRecordSet(bytes.fromhex("AABBCC"))
    ]

    with PstReader(path, pypff_module=FakePypff(pypff_file)) as reader:
        assert reader.store.uid == "aabbcc"


def test_walk_includes_bodies_only_when_requested(tmp_path: Path) -> None:
    path = tmp_path / "archive.pst"
    path.touch()

    with PstReader(path, pypff_module=FakePypff(FakePypffFile(b"store"))) as reader:
        message = list(reader.walk(include_bodies=True))[1].messages[0]

    assert message.plain_text_body == "Plain body"
    assert message.rtf_body == "RTF body"
    assert message.html_body == "<p>HTML body</p>"


def test_walk_can_select_bodies_by_message_nid(tmp_path: Path) -> None:
    path = tmp_path / "archive.pst"
    path.touch()
    pypff_file = FakePypffFile(b"store")
    selected = FakeMessage()
    selected.identifier = 201
    pypff_file.root_folder._folders[0]._messages.append(selected)

    with PstReader(path, pypff_module=FakePypff(pypff_file)) as reader:
        messages = list(reader.walk(include_body_nids={201}))[1].messages

    assert messages[0].plain_text_body is None
    assert messages[1].plain_text_body == "Plain body"


def test_attachment_metadata_and_locator_extraction_use_anonymous_fixture(
    tmp_path: Path,
) -> None:
    path = tmp_path / "archive.pst"
    path.touch()
    attachment = FakeAttachment(b"anonymous image bytes")
    message = AttachmentFakeMessage(attachment)
    pypff_file = FakePypffFile(b"store")
    pypff_file.root_folder._folders[0]._messages = [message]
    output = tmp_path / "image.png"

    with PstReader(path, pypff_module=FakePypff(pypff_file)) as reader:
        indexed = list(reader.walk(include_bodies=True))[1].messages[0]
        written = reader.extract_attachment((0,), 0, message.identifier, 0, output)

        with pytest.raises(FileExistsError):
            reader.extract_attachment((0,), 0, message.identifier, 0, output)

    assert indexed.attachments[0].filename == "anonymous-image.png"
    assert indexed.attachments[0].content_id == "<image@example.test>"
    assert indexed.attachments[0].hidden is True
    assert written == len(b"anonymous image bytes")
    assert output.read_bytes() == b"anonymous image bytes"


def test_read_message_body_uses_validated_locator_and_preferred_format(
    tmp_path: Path,
) -> None:
    path = tmp_path / "archive.pst"
    path.touch()
    pypff_file = FakePypffFile(b"store")
    source_message = pypff_file.root_folder._folders[0]._messages[0]

    with PstReader(path, pypff_module=FakePypff(pypff_file)) as reader:
        body, body_format = reader.read_message_body((0,), 0, 200)
        source_message.plain_text_body = None
        html_body, html_format = reader.read_message_body((0,), 0, 200)
        source_message.html_body = None
        rtf_body, rtf_format = reader.read_message_body((0,), 0, 200)

        with pytest.raises(pst.PstReaderError, match="does not match"):
            reader.read_message_body((0,), 0, 999)

    assert (body, body_format) == ("Plain body", "plain")
    assert (html_body, html_format) == ("<p>HTML body</p>", "html")
    assert (rtf_body, rtf_format) == ("RTF body", "rtf")


def test_attachment_adapter_handles_unavailable_metadata_and_invalid_streams(
    tmp_path: Path,
) -> None:
    path = tmp_path / "archive.pst"
    path.touch()
    reader = PstReader(path, pypff_module=FakePypff(FakePypffFile(b"store")))

    class MissingAttachment:
        number_of_attachments = 0

    class BrokenAttachment:
        @property
        def record_sets(self) -> tuple[()]:
            raise OSError("unavailable")

        @property
        def size(self) -> int:
            raise OSError("unavailable")

    assert reader._attachments(MissingAttachment()) == ()
    assert reader._attachment_entry(BrokenAttachment(), 1) is None
    assert reader._attachment_text(BrokenAttachment(), 1) is None
    assert reader._attachment_integer(BrokenAttachment(), 1) is None
    assert reader._attachment_boolean(BrokenAttachment(), 1) is None
    assert reader._attachment_size(BrokenAttachment()) is None


def test_attachment_extraction_rejects_invalid_locators_and_removes_partial_output(
    tmp_path: Path,
) -> None:
    path = tmp_path / "archive.pst"
    path.touch()
    attachment = FakeAttachment(b"short")
    attachment.size = 9
    message = AttachmentFakeMessage(attachment)
    pypff_file = FakePypffFile(b"store")
    pypff_file.root_folder._folders[0]._messages = [message]
    output = tmp_path / "partial"

    with PstReader(path, pypff_module=FakePypff(pypff_file)) as reader:
        with pytest.raises(pst.PstReaderError, match="does not match"):
            reader.extract_attachment((0,), 0, 999, 0, tmp_path / "mismatch")
        with pytest.raises(pst.PstReaderError, match="ended"):
            reader.extract_attachment((0,), 0, message.identifier, 0, output)

    assert not output.exists()


def test_attachment_extraction_rejects_missing_metadata_values(tmp_path: Path) -> None:
    path = tmp_path / "archive.pst"
    path.touch()

    class BadEntry:
        entry_type = 1

        @property
        def data_as_string(self) -> str:
            raise ValueError("bad")

        @property
        def data_as_integer(self) -> int:
            raise ValueError("bad")

        @property
        def data_as_boolean(self) -> bool:
            raise ValueError("bad")

    class BadAttachment:
        record_sets = [FakeAttachmentRecordSet([BadEntry()])]
        size = "bad"

    reader = PstReader(path, pypff_module=FakePypff(FakePypffFile(b"store")))
    assert reader._attachment_text(BadAttachment(), 1) is None
    assert reader._attachment_integer(BadAttachment(), 1) is None
    assert reader._attachment_boolean(BadAttachment(), 1) is None
    assert reader._attachment_size(BadAttachment()) is None

    pypff_file = FakePypffFile(b"store")
    pypff_file.root_folder._folders[0]._messages = [object()]  # type: ignore[list-item]
    with PstReader(path, pypff_module=FakePypff(pypff_file)) as open_reader:
        with pytest.raises(pst.PstReaderError, match="Unable to retrieve"):
            open_reader.extract_attachment((0,), 0, 200, 0, tmp_path / "x")

    pypff_file = FakePypffFile(b"store")
    pypff_file.root_folder._folders[0]._messages = [
        AttachmentFakeMessage(BadAttachment())  # type: ignore[arg-type]
    ]
    with PstReader(path, pypff_module=FakePypff(pypff_file)) as open_reader:
        with pytest.raises(pst.PstReaderError, match="usable size"):
            open_reader.extract_attachment((0,), 0, 200, 0, tmp_path / "x")


def test_walk_ignores_unavailable_optional_message_properties(tmp_path: Path) -> None:
    path = tmp_path / "archive.pst"
    path.touch()
    pypff_file = FakePypffFile(b"store")
    pypff_file.root_folder._folders[0]._messages = [SparseFakeMessage()]

    with PstReader(path, pypff_module=FakePypff(pypff_file)) as reader:
        message = list(reader.walk())[1].messages[0]

    assert message.conversation_index is None


def test_open_rejects_a_missing_pst(tmp_path: Path) -> None:
    reader = PstReader(
        tmp_path / "missing.pst",
        pypff_module=FakePypff(FakePypffFile(b"x")),
    )

    with pytest.raises(PstFileNotFoundError, match="does not exist"):
        reader.open()


def test_open_rejects_a_non_file_path(tmp_path: Path) -> None:
    reader = PstReader(tmp_path, pypff_module=FakePypff(FakePypffFile(b"x")))

    with pytest.raises(PstFileUnreadableError, match="not a regular file"):
        reader.open()


def test_open_rejects_an_os_unreadable_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "archive.pst"
    path.touch()

    def raise_permission_error(_: Path, mode: str) -> None:
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "open", raise_permission_error)
    reader = PstReader(path, pypff_module=FakePypff(FakePypffFile(b"x")))

    with pytest.raises(PstFileUnreadableError, match="cannot be read"):
        reader.open()


def test_open_wraps_pypff_read_errors(tmp_path: Path) -> None:
    path = tmp_path / "archive.pst"
    path.touch()
    reader = PstReader(
        path,
        pypff_module=FakePypff(FakePypffFile(b"x", open_error=OSError("bad PST"))),
    )

    with pytest.raises(PstFileUnreadableError, match="Unable to open PST read-only"):
        reader.open()


def test_open_requires_a_message_store_record_key(tmp_path: Path) -> None:
    path = tmp_path / "archive.pst"
    path.touch()
    pypff_file = FakePypffFile(None)

    with pytest.raises(PstStoreIdentityError, match="PidTagRecordKey"):
        PstReader(path, pypff_module=FakePypff(pypff_file)).open()

    assert pypff_file.closed


def test_reader_requires_an_open_file_and_root_folder(tmp_path: Path) -> None:
    path = tmp_path / "archive.pst"
    path.touch()
    pypff_file = FakePypffFile(b"x")
    reader = PstReader(path, pypff_module=FakePypff(pypff_file))

    with pytest.raises(Exception, match="not open"):
        _ = reader.store
    with pytest.raises(Exception, match="not open"):
        list(reader.walk())

    reader.open()
    with pytest.raises(Exception, match="already open"):
        reader.open()
    pypff_file.root_folder = None
    with pytest.raises(PstFileUnreadableError, match="no root folder"):
        list(reader.walk())
    with pytest.raises(PstFileUnreadableError, match="no root folder"):
        reader.extract_attachment((), 0, 200, 0, tmp_path / "attachment")
    reader.close()


def test_open_rejects_missing_store_and_non_bytes_record_key(tmp_path: Path) -> None:
    path = tmp_path / "archive.pst"
    path.touch()

    missing_store_file = FakePypffFile(b"x")
    missing_store_file.message_store = None
    with pytest.raises(PstStoreIdentityError, match="no message store"):
        PstReader(path, pypff_module=FakePypff(missing_store_file)).open()

    with pytest.raises(PstStoreIdentityError, match="PidTagRecordKey"):
        PstReader(path, pypff_module=FakePypff(FakePypffFile("not bytes"))).open()


def test_open_reports_a_missing_pypff_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "archive.pst"
    path.touch()

    def raise_module_not_found(_: str) -> None:
        raise ModuleNotFoundError("pypff")

    monkeypatch.setattr(pst, "import_module", raise_module_not_found)

    with pytest.raises(Exception, match="pypff is not installed"):
        PstReader(path).open()


def test_walk_rejects_a_message_without_a_nid(tmp_path: Path) -> None:
    path = tmp_path / "archive.pst"
    path.touch()
    pypff_file = FakePypffFile(b"x")
    pypff_file.root_folder.identifier = None

    with PstReader(path, pypff_module=FakePypff(pypff_file)) as reader:
        with pytest.raises(PstFileUnreadableError, match="no usable NID"):
            list(reader.walk())
