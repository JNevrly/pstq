"""Conservative extraction of Outlook-style quoted message history."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from email.utils import getaddresses, parsedate_to_datetime
from hashlib import sha256
from zoneinfo import ZoneInfo

ANALYZER_VERSION = 1

_HEADER_LABELS = {
    "from": frozenset(("from", "od", "von", "差出人")),
    "sent": frozenset(("sent", "odesláno", "gesendet", "送信日時", "送信日時")),
    "to": frozenset(("to", "komu", "an", "宛先")),
    "cc": frozenset(("cc", "kopie", "コピー")),
    "subject": frozenset(("subject", "předmět", "betreff", "件名")),
}
_HEADER_LINE = re.compile(r"^\s*([^:：]+?)\s*[:：]\s*(\S.*)$")
_FORWARDED_MARKER = re.compile(r"forwarded|weitergeleitet|přeposlan|転送", re.I)
_ORIGINAL_MESSAGE_MARKER = re.compile(r"^-+\s*original message\s*-+$", re.I)
_REPLY_PREFIX = re.compile(r"^(?:(?:re|fw|fwd|aw|wg)\s*:\s*)+", re.I)
_JAPANESE_DATE = re.compile(
    r"(?P<year>\d{4})年\s*(?P<month>\d{1,2})月\s*(?P<day>\d{1,2})日"
)
_MONTHS = {
    "ledna": "january",
    "února": "february",
    "března": "march",
    "dubna": "april",
    "května": "may",
    "června": "june",
    "července": "july",
    "srpna": "august",
    "září": "september",
    "října": "october",
    "listopadu": "november",
    "prosince": "december",
    "januar": "january",
    "februar": "february",
    "märz": "march",
    "maerz": "march",
    "april": "april",
    "mai": "may",
    "juni": "june",
    "juli": "july",
    "august": "august",
    "september": "september",
    "oktober": "october",
    "november": "november",
    "dezember": "december",
}


@dataclass(frozen=True)
class QuotedMessage:
    """One complete, high-confidence quoted Outlook message block."""

    sender: str
    sender_email: str | None
    recipients: tuple[str, ...]
    subject: str
    sent_at: str | None
    sent_raw: str
    body: str
    relation: str
    index: int

    @property
    def fingerprint(self) -> str:
        payload = "\n".join(
            (
                _canonical_sender(self.sender_email, self.sender),
                _canonical_subject(self.subject),
                _canonical_body(self.body),
            )
        )
        return sha256(payload.encode()).hexdigest()


@dataclass(frozen=True)
class BodyAnalysis:
    """The authored contribution and recognized quoted messages in one body."""

    authored_body: str
    quoted_messages: tuple[QuotedMessage, ...]


def analyze_body(body: str | bytes | None, timezone_name: str) -> BodyAnalysis:
    """Extract only complete Outlook header blocks from BODY.

    Header labels must occur in their localized Outlook order, although blank
    presentation lines are tolerated because Outlook HTML often introduces them.
    """
    text = _text(body)
    if not text:
        return BodyAnalysis(text, ())
    lines = text.splitlines(keepends=True)
    candidates: list[tuple[int, int, dict[str, str]]] = []
    position = 0
    while position < len(lines):
        parsed = _header_block(lines, position)
        if parsed is None:
            position += 1
            continue
        end, headers = parsed
        candidates.append((position, end, headers))
        position = end
    if not candidates:
        return BodyAnalysis(text, ())

    quotes: list[QuotedMessage] = []
    for quote_index, (start, header_end, headers) in enumerate(candidates):
        body_end = (
            candidates[quote_index + 1][0]
            if quote_index + 1 < len(candidates)
            else len(lines)
        )
        quoted_body = "".join(lines[header_end:body_end]).strip()
        sender_email = _email(headers["from"])
        recipients = tuple(
            address for _, address in getaddresses((headers["to"],)) if address
        )
        quotes.append(
            QuotedMessage(
                sender=headers["from"],
                sender_email=sender_email,
                recipients=recipients,
                subject=headers["subject"],
                sent_at=_parse_date(headers["sent"], timezone_name),
                sent_raw=headers["sent"],
                body=quoted_body,
                relation=_relation(lines, start),
                index=quote_index,
            )
        )
    authored_end = _authored_end(lines, candidates[0][0])
    return BodyAnalysis("".join(lines[:authored_end]), tuple(quotes))


def is_owner(
    quote: QuotedMessage, emails: frozenset[str], names: frozenset[str]
) -> bool:
    """Return whether a parsed quote has an explicitly configured owner alias."""
    return (
        quote.sender_email is not None and quote.sender_email.casefold() in emails
    ) or _normalized_sender_name(quote.sender) in names


def native_fingerprint(
    sender: str | None,
    sender_email: str | None,
    subject: str | None,
    body: str | bytes | None,
) -> str:
    """Return the canonical identity used to suppress exact native duplicates."""
    payload = "\n".join(
        (
            _canonical_sender(sender_email, sender or ""),
            _canonical_subject(subject or ""),
            _canonical_body(_text(body)),
        )
    )
    return sha256(payload.encode()).hexdigest()


def _header_block(lines: list[str], start: int) -> tuple[int, dict[str, str]] | None:
    headers: dict[str, str] = {}
    position = start
    for expected in ("from", "sent", "to"):
        position = _skip_empty(lines, position)
        if position >= len(lines):
            return None
        field = _field(lines[position])
        if field is None or field[0] != expected:
            return None
        headers[expected] = field[1]
        position += 1
    position = _skip_empty(lines, position)
    if position < len(lines):
        field = _field(lines[position])
        if field is not None and field[0] == "cc":
            headers["cc"] = field[1]
            position += 1
    position = _skip_empty(lines, position)
    if position >= len(lines):
        return None
    field = _field(lines[position])
    if field is None or field[0] != "subject":
        return None
    headers["subject"] = field[1]
    return position + 1, headers


def _skip_empty(lines: list[str], position: int) -> int:
    while position < len(lines) and not lines[position].strip():
        position += 1
    return position


def _field(line: str) -> tuple[str, str] | None:
    match = _HEADER_LINE.fullmatch(line.strip())
    if match is None:
        return None
    label = match[1].casefold()
    for name, labels in _HEADER_LABELS.items():
        if label in labels:
            return name, match[2].strip()
    return None


def _relation(lines: list[str], start: int) -> str:
    nearby = " ".join(line.strip() for line in lines[max(0, start - 3) : start])
    return "forwarded_context" if _FORWARDED_MARKER.search(nearby) else "reply_history"


def _authored_end(lines: list[str], start: int) -> int:
    if start and _ORIGINAL_MESSAGE_MARKER.fullmatch(lines[start - 1].strip()):
        return start - 1
    return start


def _parse_date(value: str, timezone_name: str) -> str | None:
    value = _JAPANESE_DATE.sub(r"\g<year>-\g<month>-\g<day>", value)
    for source, replacement in _MONTHS.items():
        value = re.sub(rf"\b{re.escape(source)}\b", replacement, value, flags=re.I)
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        parsed = None
    if parsed is None:
        for pattern in (
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%d.%m.%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y %H:%M:%S",
        ):
            try:
                parsed = datetime.strptime(value.strip(), pattern)
            except ValueError:
                continue
            break
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.isoformat()


def _email(value: str) -> str | None:
    addresses = getaddresses((value,))
    return addresses[0][1].casefold() if addresses and addresses[0][1] else None


def _normalized_sender_name(value: str) -> str:
    addresses = getaddresses((value,))
    return _normalized(addresses[0][0] if addresses and addresses[0][0] else value)


def _text(value: str | bytes | None) -> str:
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value or ""


def _canonical_sender(email: str | None, sender: str) -> str:
    return (email or _normalized(sender)).casefold()


def _canonical_subject(value: str) -> str:
    return _normalized(_REPLY_PREFIX.sub("", value))


def _canonical_body(value: str) -> str:
    return "\n".join(" ".join(line.split()) for line in value.splitlines()).strip()


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()
