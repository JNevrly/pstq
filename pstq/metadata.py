"""Metadata-only PST inspection, snapshotting, and comparison."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from importlib import import_module
from pathlib import Path
from time import perf_counter
from typing import Any

from pstq.pst import PstReader

SNAPSHOT_FORMAT_VERSION = 1


class SnapshotFormatError(ValueError):
    """Raised when a metadata snapshot does not have the expected structure."""


@dataclass(frozen=True)
class FolderMetadata:
    """The folder fields retained in a durable metadata snapshot."""

    nid: int
    path: str

    def as_dict(self) -> dict[str, object]:
        return {"nid": self.nid, "path": self.path}


@dataclass(frozen=True)
class MessageMetadata:
    """The message fields retained in a durable metadata snapshot."""

    nid: int
    folder_nid: int
    modification_time: str | None

    def as_dict(self) -> dict[str, object]:
        return {
            "folder_nid": self.folder_nid,
            "modification_time": self.modification_time,
            "nid": self.nid,
        }


@dataclass(frozen=True)
class MetadataSnapshot:
    """A portable, body-free representation of a PST's metadata."""

    store_uid: str
    folders: tuple[FolderMetadata, ...]
    messages: tuple[MessageMetadata, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "folders": [folder.as_dict() for folder in self.folders],
            "format_version": SNAPSHOT_FORMAT_VERSION,
            "messages": [message.as_dict() for message in self.messages],
            "store_uid": self.store_uid,
        }


@dataclass(frozen=True)
class Inspection:
    """Results of one metadata traversal."""

    libpff_version: str
    pst_size: int
    store_uid: str
    folder_count: int
    message_count: int
    duration_seconds: float
    messages_per_second: float | None
    scan_errors: tuple[str, ...]
    samples: tuple[dict[str, object], ...]
    snapshot: MetadataSnapshot

    def as_dict(self) -> dict[str, object]:
        return {
            "duration_seconds": self.duration_seconds,
            "folder_count": self.folder_count,
            "libpff_version": self.libpff_version,
            "message_count": self.message_count,
            "messages_per_second": self.messages_per_second,
            "pst_size": self.pst_size,
            "samples": list(self.samples),
            "scan_errors": list(self.scan_errors),
            "store_uid": self.store_uid,
        }


def inspect_pst(path: str | Path, *, sample_size: int = 10) -> Inspection:
    """Traverse a PST without asking the adapter to read message bodies."""
    if sample_size < 0:
        raise ValueError("sample_size must not be negative")

    pst_path = Path(path)
    pst_size = pst_path.stat().st_size
    folders: list[FolderMetadata] = []
    messages: list[MessageMetadata] = []
    samples: list[dict[str, object]] = []
    scan_errors: list[str] = []
    started_at = perf_counter()

    with PstReader(pst_path) as reader:
        store_uid = reader.store.uid
        try:
            for folder in reader.walk():
                folders.append(FolderMetadata(nid=folder.nid, path=folder.path))
                for message in folder.messages:
                    modification_time = _format_time(message.modification_time)
                    messages.append(
                        MessageMetadata(
                            nid=message.nid,
                            folder_nid=message.folder_nid,
                            modification_time=modification_time,
                        )
                    )
                    if len(samples) < sample_size:
                        samples.append(
                            {
                                "folder_nid": message.folder_nid,
                                "folder_path": folder.path,
                                "modification_time": modification_time,
                                "nid": message.nid,
                                "subject": message.subject,
                            }
                        )
        except Exception as error:
            scan_errors.append(f"{type(error).__name__}: {error}")

    duration_seconds = perf_counter() - started_at
    message_count = len(messages)
    snapshot = MetadataSnapshot(
        store_uid=store_uid,
        folders=tuple(sorted(folders, key=lambda folder: (folder.path, folder.nid))),
        messages=tuple(
            sorted(
                messages,
                key=lambda message: (
                    message.nid,
                    message.folder_nid,
                    message.modification_time or "",
                ),
            )
        ),
    )
    return Inspection(
        libpff_version=_libpff_version(),
        pst_size=pst_size,
        store_uid=store_uid,
        folder_count=len(folders),
        message_count=message_count,
        duration_seconds=duration_seconds,
        messages_per_second=(
            message_count / duration_seconds if duration_seconds else None
        ),
        scan_errors=tuple(scan_errors),
        samples=tuple(samples),
        snapshot=snapshot,
    )


def write_snapshot(snapshot: MetadataSnapshot, path: str | Path) -> None:
    """Write a stable JSON snapshot without including volatile scan measurements."""
    Path(path).write_text(_json(snapshot.as_dict()), encoding="utf-8")


def read_snapshot(path: str | Path) -> MetadataSnapshot:
    """Load a metadata snapshot produced by :func:`write_snapshot`."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SnapshotFormatError(f"Unable to read snapshot {path}: {error}") from error
    if not isinstance(raw, dict):
        raise SnapshotFormatError("Snapshot root must be an object")
    if raw.get("format_version") != SNAPSHOT_FORMAT_VERSION:
        raise SnapshotFormatError(
            f"Unsupported snapshot format version: {raw.get('format_version')!r}"
        )

    store_uid = raw.get("store_uid")
    folders = raw.get("folders")
    messages = raw.get("messages")
    if not isinstance(store_uid, str):
        raise SnapshotFormatError("Snapshot store_uid must be a string")
    if not isinstance(folders, list) or not isinstance(messages, list):
        raise SnapshotFormatError("Snapshot folders and messages must be arrays")

    return MetadataSnapshot(
        store_uid=store_uid,
        folders=tuple(_folder_from_dict(folder) for folder in folders),
        messages=tuple(_message_from_dict(message) for message in messages),
    )


def compare_snapshots(
    before: MetadataSnapshot, after: MetadataSnapshot
) -> dict[str, object]:
    """Classify message changes while surfacing unreliable identity assumptions."""
    before_messages, before_issues = _unique_messages(before)
    after_messages, after_issues = _unique_messages(after)

    before_ids = set(before_messages)
    after_ids = set(after_messages)
    common_ids = before_ids & after_ids
    modified = []
    moved = []
    unchanged = []
    for nid in sorted(common_ids):
        before_message = before_messages[nid]
        after_message = after_messages[nid]
        if before_message.modification_time != after_message.modification_time:
            modified.append(
                {
                    "after_modification_time": after_message.modification_time,
                    "before_modification_time": before_message.modification_time,
                    "nid": nid,
                }
            )
        if before_message.folder_nid != after_message.folder_nid:
            moved.append(
                {
                    "after_folder_nid": after_message.folder_nid,
                    "before_folder_nid": before_message.folder_nid,
                    "nid": nid,
                }
            )
        if (
            before_message.modification_time == after_message.modification_time
            and before_message.folder_nid == after_message.folder_nid
        ):
            unchanged.append(nid)

    return {
        "after_store_uid": after.store_uid,
        "before_store_uid": before.store_uid,
        "missing": [
            before_messages[nid].as_dict() for nid in sorted(before_ids - after_ids)
        ],
        "modified": modified,
        "moved": moved,
        "new": [
            after_messages[nid].as_dict() for nid in sorted(after_ids - before_ids)
        ],
        "suspicious_identity": {
            "after": after_issues,
            "before": before_issues,
            "store_uid_changed": before.store_uid != after.store_uid,
        },
        "unchanged": {"count": len(unchanged)},
    }


def _format_time(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _libpff_version() -> str:
    try:
        pypff = import_module("pypff")
        get_version = getattr(pypff, "get_version", None)
        return str(get_version()) if callable(get_version) else "unknown"
    except (ImportError, OSError):
        return "unknown"


def _folder_from_dict(raw: object) -> FolderMetadata:
    if not isinstance(raw, dict):
        raise SnapshotFormatError("Each snapshot folder must be an object")
    nid = raw.get("nid")
    path = raw.get("path")
    if not isinstance(nid, int) or not isinstance(path, str):
        raise SnapshotFormatError(
            "Each snapshot folder needs integer nid and string path"
        )
    return FolderMetadata(nid=nid, path=path)


def _message_from_dict(raw: object) -> MessageMetadata:
    if not isinstance(raw, dict):
        raise SnapshotFormatError("Each snapshot message must be an object")
    nid = raw.get("nid")
    folder_nid = raw.get("folder_nid")
    modification_time = raw.get("modification_time")
    if not isinstance(nid, int) or not isinstance(folder_nid, int):
        raise SnapshotFormatError(
            "Each snapshot message needs integer nid and folder_nid"
        )
    if modification_time is not None and not isinstance(modification_time, str):
        raise SnapshotFormatError("Snapshot modification_time must be a string or null")
    return MessageMetadata(
        nid=nid,
        folder_nid=folder_nid,
        modification_time=modification_time,
    )


def _unique_messages(
    snapshot: MetadataSnapshot,
) -> tuple[dict[int, MessageMetadata], dict[str, list[int]]]:
    folder_nids = [folder.nid for folder in snapshot.folders]
    duplicate_folder_nids = _duplicates(folder_nids)
    message_nids = [message.nid for message in snapshot.messages]
    duplicate_message_nids = _duplicates(message_nids)
    duplicate_nid_set = set(duplicate_message_nids)
    unique_messages = {
        message.nid: message
        for message in snapshot.messages
        if message.nid not in duplicate_nid_set
    }
    known_folder_nids = set(folder_nids)
    missing_folder_nids = sorted(
        message.nid
        for message in snapshot.messages
        if message.folder_nid not in known_folder_nids
    )
    return unique_messages, {
        "duplicate_folder_nids": duplicate_folder_nids,
        "duplicate_message_nids": duplicate_message_nids,
        "messages_with_unknown_folder_nids": missing_folder_nids,
    }


def _duplicates(values: list[int]) -> list[int]:
    seen: set[int] = set()
    duplicates: set[int] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return sorted(duplicates)


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"
