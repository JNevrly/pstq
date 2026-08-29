"""Read-only adapter between pypff and PST Query records."""

from __future__ import annotations

from collections.abc import Collection, Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, Self, cast

PID_TAG_RECORD_KEY = 0x0FF9
PID_TAG_CONVERSATION_TOPIC = 0x0070
PID_TAG_CONVERSATION_INDEX = 0x0071
PID_TAG_INTERNET_MESSAGE_ID = 0x1035
PID_TAG_INTERNET_REFERENCES = 0x1039
PID_TAG_IN_REPLY_TO_ID = 0x1042
PID_TAG_ATTACH_FILENAME = 0x3704
PID_TAG_ATTACH_METHOD = 0x3705
PID_TAG_ATTACH_LONG_FILENAME = 0x3707
PID_TAG_RENDERING_POSITION = 0x370B
PID_TAG_ATTACH_MIME_TAG = 0x370E
PID_TAG_ATTACH_CONTENT_ID = 0x3712
PID_TAG_ATTACH_CONTENT_LOCATION = 0x3713
PID_TAG_ATTACHMENT_HIDDEN = 0x7FFE


class PstReaderError(RuntimeError):
    """Base error raised when a PST cannot be read safely."""


class PstFileNotFoundError(PstReaderError):
    """Raised when the configured PST path does not exist."""


class PstFileUnreadableError(PstReaderError):
    """Raised when libpff cannot open a PST in read-only mode."""


class PstStoreIdentityError(PstReaderError):
    """Raised when a PST does not expose its message-store record key."""


class _PypffFile(Protocol):
    message_store: Any
    root_folder: Any

    def close(self) -> None: ...

    def open(self, filename: str, mode: str = "r") -> None: ...


class _PypffModule(Protocol):
    def file(self) -> _PypffFile: ...


@dataclass(frozen=True)
class PstStore:
    """Stable identity of a message store."""

    uid: str


@dataclass(frozen=True)
class PstAttachment:
    """Metadata for one attachment without its binary payload."""

    index: int
    filename: str | None
    mime_type: str | None
    size: int | None
    content_id: str | None
    content_location: str | None
    attachment_method: int | None
    hidden: bool | None
    rendering_position: int | None


@dataclass(frozen=True)
class PstMessage:
    """A normalized message and the mail properties pypff exposes directly."""

    nid: int
    folder_nid: int
    modification_time: datetime | None
    subject: str | None
    sender_name: str | None
    client_submit_time: datetime | None
    delivery_time: datetime | None
    transport_headers: str | None
    conversation_topic: str | None
    conversation_index: str | None
    attachment_count: int
    plain_text_body: str | bytes | None
    rtf_body: str | bytes | None
    html_body: str | bytes | None
    attachments: tuple[PstAttachment, ...] = ()
    index_in_folder: int = 0
    internet_message_id: str | None = None
    in_reply_to: str | None = None
    references_header: str | None = None


@dataclass(frozen=True)
class PstFolder:
    """A normalized folder and its direct messages."""

    nid: int
    parent_nid: int | None
    name: str | None
    path: str
    messages: tuple[PstMessage, ...]
    index_in_parent: int | None = None


class PstReader:
    """Open and traverse a PST without exposing pypff objects to callers."""

    def __init__(
        self,
        path: str | Path,
        *,
        pypff_module: _PypffModule | None = None,
    ) -> None:
        self.path = Path(path)
        self._pypff_module = pypff_module
        self._file: _PypffFile | None = None
        self._store: PstStore | None = None

    def __enter__(self) -> Self:
        return self.open()

    def __exit__(self, *_: object) -> None:
        self.close()

    @property
    def store(self) -> PstStore:
        """Return the open PST's message-store identity."""
        if self._store is None:
            raise PstReaderError("PST is not open.")
        return self._store

    def open(self) -> Self:
        """Open the configured regular file in pypff's read-only mode."""
        if self._file is not None:
            raise PstReaderError(f"PST is already open: {self.path}")
        if not self.path.exists():
            raise PstFileNotFoundError(f"PST file does not exist: {self.path}")
        if not self.path.is_file():
            raise PstFileUnreadableError(f"PST path is not a regular file: {self.path}")

        try:
            with self.path.open("rb"):
                pass
        except OSError as error:
            raise PstFileUnreadableError(
                f"PST file cannot be read: {self.path}: {error}"
            ) from error

        pypff_module = self._pypff_module or self._load_pypff()
        pff_file = pypff_module.file()
        try:
            pff_file.open(str(self.path), mode="r")
        except (OSError, RuntimeError, ValueError) as error:
            raise PstFileUnreadableError(
                f"Unable to open PST read-only: {self.path}: {error}"
            ) from error

        self._file = pff_file
        try:
            self._store = PstStore(uid=self._message_store_uid(pff_file.message_store))
        except Exception:
            self.close()
            raise
        return self

    def close(self) -> None:
        """Close the underlying pypff handle when it is open."""
        if self._file is not None:
            try:
                self._file.close()
            finally:
                self._file = None
                self._store = None

    def walk(
        self,
        *,
        include_bodies: bool = False,
        include_body_nids: Collection[int] | None = None,
    ) -> Iterator[PstFolder]:
        """Yield folders depth-first with normalized direct-message records.

        Bodies are opt-in so metadata scans do not read them accidentally.  A
        caller can instead select just the message NIDs whose bodies it needs.
        """
        pff_file = self._require_open()
        root_folder = pff_file.root_folder
        if root_folder is None:
            raise PstFileUnreadableError(f"PST has no root folder: {self.path}")
        yield from self._walk_folder(
            root_folder,
            parent_nid=None,
            parent_path="",
            index_in_parent=None,
            include_bodies=include_bodies,
            include_body_nids=frozenset(include_body_nids or ()),
        )

    def _walk_folder(
        self,
        folder: Any,
        *,
        parent_nid: int | None,
        parent_path: str,
        index_in_parent: int | None,
        include_bodies: bool,
        include_body_nids: frozenset[int],
    ) -> Iterator[PstFolder]:
        nid = self._nid(folder, "folder")
        name = cast(str | None, self._optional_property(folder, "name"))
        path = "/".join(part for part in (parent_path, name) if part)
        messages = tuple(
            self._message_from_pypff(
                folder.get_sub_message(index),
                folder_nid=nid,
                index_in_folder=index,
                include_bodies=include_bodies,
                include_body_nids=include_body_nids,
            )
            for index in range(folder.number_of_sub_messages)
        )
        yield PstFolder(
            nid=nid,
            parent_nid=parent_nid,
            name=name,
            path=path,
            messages=messages,
            index_in_parent=index_in_parent,
        )

        for index in range(folder.number_of_sub_folders):
            yield from self._walk_folder(
                folder.get_sub_folder(index),
                parent_nid=nid,
                parent_path=path,
                index_in_parent=index,
                include_bodies=include_bodies,
                include_body_nids=include_body_nids,
            )

    def _message_from_pypff(
        self,
        message: Any,
        *,
        folder_nid: int,
        index_in_folder: int,
        include_bodies: bool,
        include_body_nids: frozenset[int],
    ) -> PstMessage:
        conversation_index = self._message_bytes(message, PID_TAG_CONVERSATION_INDEX)
        nid = self._nid(message, "message")
        should_include_body = include_bodies or nid in include_body_nids
        return PstMessage(
            nid=nid,
            folder_nid=folder_nid,
            modification_time=self._optional_property(message, "modification_time"),
            subject=self._optional_property(message, "subject"),
            sender_name=self._optional_property(message, "sender_name"),
            client_submit_time=self._optional_property(message, "client_submit_time"),
            delivery_time=self._optional_property(message, "delivery_time"),
            transport_headers=self._optional_property(message, "transport_headers"),
            conversation_topic=(
                self._message_text(message, PID_TAG_CONVERSATION_TOPIC)
                or self._optional_property(message, "conversation_topic")
            ),
            conversation_index=(
                bytes(conversation_index).hex()
                if conversation_index is not None
                else None
            ),
            attachment_count=self._optional_property(message, "number_of_attachments")
            or 0,
            plain_text_body=(
                self._optional_property(message, "plain_text_body")
                if should_include_body
                else None
            ),
            rtf_body=(
                self._optional_property(message, "rtf_body")
                if should_include_body
                else None
            ),
            html_body=(
                self._optional_property(message, "html_body")
                if should_include_body
                else None
            ),
            attachments=self._attachments(message) if should_include_body else (),
            index_in_folder=index_in_folder,
            internet_message_id=self._message_text(
                message, PID_TAG_INTERNET_MESSAGE_ID
            ),
            in_reply_to=self._message_text(message, PID_TAG_IN_REPLY_TO_ID),
            references_header=self._message_text(message, PID_TAG_INTERNET_REFERENCES),
        )

    def extract_attachment(
        self,
        folder_indexes: Sequence[int],
        message_index: int,
        message_nid: int,
        attachment_index: int,
        output_path: str | Path,
    ) -> int:
        """Write an attachment through a cached stock-pypff traversal locator."""
        folder = self._require_open().root_folder
        if folder is None:
            raise PstFileUnreadableError(f"PST has no root folder: {self.path}")
        try:
            for folder_index in folder_indexes:
                folder = folder.get_sub_folder(folder_index)
            message = folder.get_sub_message(message_index)
            if self._nid(message, "message") != message_nid:
                raise PstReaderError(
                    f"Cached locator does not match message {message_nid}."
                )
            attachment = message.get_attachment(attachment_index)
            size = attachment.size
        except (AttributeError, IndexError, OSError) as error:
            raise PstReaderError(
                f"Unable to retrieve attachment {attachment_index} "
                f"for message {message_nid}."
            ) from error
        if not isinstance(size, int) or size < 0:
            raise PstReaderError(
                f"Attachment {attachment_index} for message {message_nid} "
                "has no usable size."
            )
        destination = Path(output_path)
        written = 0
        try:
            output = destination.open("xb")
        except FileExistsError:
            raise
        try:
            with output:
                while written < size:
                    chunk = attachment.read_buffer(min(64 * 1024, size - written))
                    if not chunk:
                        raise PstReaderError(
                            f"Attachment {attachment_index} ended before "
                            "its expected size."
                        )
                    output.write(chunk)
                    written += len(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        return written

    def _attachments(self, message: Any) -> tuple[PstAttachment, ...]:
        count = self._optional_property(message, "number_of_attachments") or 0
        if not isinstance(count, int) or count < 1:
            return ()
        attachments: list[PstAttachment] = []
        for index in range(count):
            try:
                attachment = message.get_attachment(index)
            except (AttributeError, OSError):
                continue
            attachments.append(
                PstAttachment(
                    index=index,
                    filename=(
                        self._attachment_text(attachment, PID_TAG_ATTACH_LONG_FILENAME)
                        or self._attachment_text(attachment, PID_TAG_ATTACH_FILENAME)
                    ),
                    mime_type=self._attachment_text(
                        attachment, PID_TAG_ATTACH_MIME_TAG
                    ),
                    size=self._attachment_size(attachment),
                    content_id=self._attachment_text(
                        attachment, PID_TAG_ATTACH_CONTENT_ID
                    ),
                    content_location=self._attachment_text(
                        attachment, PID_TAG_ATTACH_CONTENT_LOCATION
                    ),
                    attachment_method=self._attachment_integer(
                        attachment, PID_TAG_ATTACH_METHOD
                    ),
                    hidden=self._attachment_boolean(
                        attachment, PID_TAG_ATTACHMENT_HIDDEN
                    ),
                    rendering_position=self._attachment_integer(
                        attachment, PID_TAG_RENDERING_POSITION
                    ),
                )
            )
        return tuple(attachments)

    def _attachment_entry(self, attachment: Any, property_tag: int) -> Any:
        try:
            for record_set in attachment.record_sets:
                for entry in record_set.entries:
                    if entry.entry_type == property_tag:
                        return entry
        except (AttributeError, OSError):
            pass
        return None

    def _message_entry(self, message: Any, property_tag: int) -> Any:
        try:
            for record_set in message.record_sets:
                get_entry_by_type = getattr(record_set, "get_entry_by_type", None)
                if get_entry_by_type is not None:
                    entry = get_entry_by_type(property_tag)
                    if entry is not None:
                        return entry
                    continue
                for entry in record_set.entries:
                    if entry.entry_type == property_tag:
                        return entry
        except (AttributeError, OSError):
            pass
        return None

    def _message_text(self, message: Any, property_tag: int) -> str | None:
        entry = self._message_entry(message, property_tag)
        if entry is None:
            return None
        try:
            value = entry.data_as_string
        except (AttributeError, OSError, ValueError):
            return None
        return value if isinstance(value, str) and value else None

    def _message_bytes(self, message: Any, property_tag: int) -> bytes | None:
        entry = self._message_entry(message, property_tag)
        if entry is not None:
            try:
                value = bytes(entry.data)
            except (AttributeError, OSError, TypeError, ValueError):
                value = None
            if value:
                return value
        value = self._optional_property(message, "conversation_index")
        try:
            return bytes(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _attachment_text(self, attachment: Any, property_tag: int) -> str | None:
        entry = self._attachment_entry(attachment, property_tag)
        if entry is None:
            return None
        try:
            value = entry.data_as_string
        except (AttributeError, OSError, ValueError):
            return None
        return value if isinstance(value, str) and value else None

    def _attachment_integer(self, attachment: Any, property_tag: int) -> int | None:
        entry = self._attachment_entry(attachment, property_tag)
        if entry is None:
            return None
        try:
            value = entry.data_as_integer
        except (AttributeError, OSError, ValueError):
            return None
        return value if isinstance(value, int) else None

    def _attachment_boolean(self, attachment: Any, property_tag: int) -> bool | None:
        entry = self._attachment_entry(attachment, property_tag)
        if entry is None:
            return None
        try:
            value = entry.data_as_boolean
        except (AttributeError, OSError, ValueError):
            return None
        return value if isinstance(value, bool) else None

    def _attachment_size(self, attachment: Any) -> int | None:
        try:
            size = attachment.size
        except (AttributeError, OSError):
            return None
        return size if isinstance(size, int) and size >= 0 else None

    def _message_store_uid(self, message_store: Any) -> str:
        if message_store is None:
            raise PstStoreIdentityError(f"PST has no message store: {self.path}")

        for record_set in message_store.record_sets:
            entry = self._record_key_entry(record_set)
            if entry is not None:
                value = entry.data
                if isinstance(value, bytes) and value:
                    return value.hex()

        raise PstStoreIdentityError(
            f"PST message store has no PidTagRecordKey (0x{PID_TAG_RECORD_KEY:04x}): "
            f"{self.path}"
        )

    def _record_key_entry(self, record_set: Any) -> Any:
        get_entry_by_type = getattr(record_set, "get_entry_by_type", None)
        if get_entry_by_type is not None:
            return get_entry_by_type(PID_TAG_RECORD_KEY)

        return next(
            (
                entry
                for entry in record_set.entries
                if entry.entry_type == PID_TAG_RECORD_KEY
            ),
            None,
        )

    def _require_open(self) -> _PypffFile:
        if self._file is None:
            raise PstReaderError("PST is not open.")
        return self._file

    def _load_pypff(self) -> _PypffModule:
        try:
            return cast(_PypffModule, import_module("pypff"))
        except ModuleNotFoundError as error:
            raise PstReaderError(
                "pypff is not installed. Rebuild the devcontainer or install its "
                "pinned libpff wheel."
            ) from error

    def _nid(self, item: Any, item_type: str) -> int:
        identifier = item.identifier
        if not isinstance(identifier, int):
            raise PstFileUnreadableError(
                f"PST {item_type} has no usable NID: {self.path}"
            )
        return identifier

    def _optional_property(self, item: Any, name: str) -> Any:
        try:
            return getattr(item, name)
        except (AttributeError, OSError):
            return None
