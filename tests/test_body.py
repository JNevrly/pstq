"""Tests for conservative quoted Outlook-history recovery."""

from __future__ import annotations

import pytest

from pstq.body import analyze_body, is_owner


@pytest.mark.parametrize(
    ("headers", "expected_subject"),
    [
        (
            "From: Owner <owner@example.test>\nSent: 20.08.2026 10:00\n"
            "To: Recipient <recipient@example.test>\nSubject: Status",
            "Status",
        ),
        (
            "Od: Owner <owner@example.test>\nOdesláno: 20.08.2026 10:00\n"
            "Komu: Recipient <recipient@example.test>\nPředmět: Stav",
            "Stav",
        ),
        (
            "Von: Owner <owner@example.test>\nGesendet: 20.08.2026 10:00\n"
            "An: Recipient <recipient@example.test>\nBetreff: Status",
            "Status",
        ),
        (
            "差出人: Owner <owner@example.test>\n送信日時: 2026年8月20日 10:00\n"
            "宛先: Recipient <recipient@example.test>\n件名: 状況",
            "状況",
        ),
    ],
)
def test_analyze_body_recovers_localized_outlook_headers(
    headers: str, expected_subject: str
) -> None:
    analysis = analyze_body(
        f"Current contribution\n-----Original Message-----\n{headers}\nQuoted",
        "Europe/Prague",
    )

    assert analysis.authored_body == "Current contribution\n"
    assert len(analysis.quoted_messages) == 1
    quote = analysis.quoted_messages[0]
    assert quote.subject == expected_subject
    assert quote.sender_email == "owner@example.test"
    assert quote.body == "Quoted"
    assert quote.sent_at == "2026-08-20T10:00:00+02:00"


def test_analyze_body_accepts_html_rendering_gaps_and_marks_forwarded_context() -> None:
    analysis = analyze_body(
        "Current\n----- Forwarded message -----\nFrom: Owner <owner@example.test>\n\n"
        "Sent: 20.08.2026 10:00\n\nTo: Recipient <recipient@example.test>\n\n"
        "Subject: Forwarded\nQuoted",
        "Europe/Prague",
    )

    assert analysis.quoted_messages[0].relation == "forwarded_context"
    assert analysis.quoted_messages[0].body == "Quoted"


def test_analyze_body_keeps_incomplete_header_like_content_authored() -> None:
    body = "Draft notes\nFrom: someone\nTo: recipient\nSubject: not an email"

    assert analyze_body(body, "UTC").authored_body == body
    assert analyze_body(body, "UTC").quoted_messages == ()


def test_analyze_body_handles_empty_bytes_and_unparseable_dates() -> None:
    assert analyze_body(None, "UTC").authored_body == ""
    assert analyze_body(b"ordinary bytes", "UTC").authored_body == "ordinary bytes"
    assert (
        analyze_body(
            "From: Owner\nSent: someday\nTo: Recipient\nSubject: Subject\nBody",
            "UTC",
        )
        .quoted_messages[0]
        .sent_at
        is None
    )
    assert (
        analyze_body(
            "From: Owner\nSent: 20.08.2026 10:00\nTo: Recipient\nNo subject",
            "UTC",
        ).quoted_messages
        == ()
    )
    analysis = analyze_body(
        "Current\n\nFrom: Owner\nSent: 20.08.2026 10:00\nTo: Recipient\n"
        "Subject: Subject\nBody",
        "UTC",
    )
    assert analysis.authored_body == "Current\n"


def test_owner_matching_prefers_email_and_supports_explicit_name() -> None:
    email_quote = analyze_body(
        "From: Owner <owner@example.test>\nSent: 20.08.2026 10:00\n"
        "To: Recipient\nSubject: Subject\nBody",
        "UTC",
    ).quoted_messages[0]
    name_quote = analyze_body(
        "From: Owner\nSent: 20.08.2026 10:00\nTo: Recipient\nSubject: Subject\nBody",
        "UTC",
    ).quoted_messages[0]

    assert is_owner(email_quote, frozenset(("owner@example.test",)), frozenset())
    assert is_owner(name_quote, frozenset(), frozenset(("owner",)))
