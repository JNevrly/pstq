"""Read-only adapter between pypff and PST Query records."""

from __future__ import annotations

from collections.abc import Collection, Iterator
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, Self, cast

PID_TAG_RECORD_KEY = 0x0FF9


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
    plain_text_body: str | None
    rtf_body: str | None
    html_body: str | None


@dataclass(frozen=True)
class PstFolder:
    """A normalized folder and its direct messages."""

    nid: int
    parent_nid: int | None
    name: str | None
    path: str
    messages: tuple[PstMessage, ...]


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
            include_bodies=include_bodies,
            include_body_nids=frozenset(include_body_nids or ()),
        )

    def _walk_folder(
        self,
        folder: Any,
        *,
        parent_nid: int | None,
        parent_path: str,
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
        )

        for index in range(folder.number_of_sub_folders):
            yield from self._walk_folder(
                folder.get_sub_folder(index),
                parent_nid=nid,
                parent_path=path,
                include_bodies=include_bodies,
                include_body_nids=include_body_nids,
            )

    def _message_from_pypff(
        self,
        message: Any,
        *,
        folder_nid: int,
        include_bodies: bool,
        include_body_nids: frozenset[int],
    ) -> PstMessage:
        conversation_index = self._optional_property(message, "conversation_index")
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
            conversation_topic=self._optional_property(message, "conversation_topic"),
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
        )

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
