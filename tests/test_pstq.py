#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for the package and CLI."""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner
from onacol import ConfigValidationError

from pstq import cli, pstq
from pstq.index import SearchResult


@pytest.fixture
def response():
    """Sample pytest fixture.

    See more at: http://doc.pytest.org/en/latest/fixture.html
    """
    # import requests
    # return requests.get('https://github.com/audreyr/cookiecutter-pypackage')


def test_content(response):
    """Sample pytest test function with the pytest fixture as an argument."""
    # from bs4 import BeautifulSoup
    # assert 'GitHub' in BeautifulSoup(response.content).title.string
    assert pstq.hello() == "Hello from PST Query"


def test_command_line_interface():
    """Every command exposes its agent-facing contract through --help."""
    runner = CliRunner()
    result = runner.invoke(cli.main, ["--help"])
    assert result.exit_code == 0
    assert "compare-snapshots" in result.output
    assert "inspect" in result.output
    assert "snapshot" in result.output
    assert "PSTQ_ARCHIVE__PST_PATH" in result.output
    assert "STORE_UID:NID" in result.output
    assert "--offset" in runner.invoke(cli.main, ["search", "--help"]).output

    for command in (
        "status",
        "folders",
        "search",
        "show",
        "thread",
        "attachments",
        "attachment",
    ):
        command_help = runner.invoke(cli.main, [command, "--help"])
        assert command_help.exit_code == 0
        assert "--json" in command_help.output


def test_inspect_command_outputs_deterministic_json(monkeypatch):
    class Report:
        def as_dict(self):
            return {"z": 1, "a": 2}

    monkeypatch.setattr(cli, "inspect_pst", lambda *_args, **_kwargs: Report())

    result = CliRunner().invoke(cli.main, ["inspect", "archive.pst", "--json"])

    assert result.exit_code == 0
    assert result.output == '{\n  "a": 2,\n  "z": 1\n}\n'


def test_inspect_command_outputs_human_report(monkeypatch):
    class Report:
        libpff_version = "20231205"
        pst_size = 1
        store_uid = "store"
        folder_count = 2
        message_count = 3
        duration_seconds = 0.5
        messages_per_second = 6.0
        scan_errors = ("OSError: broken",)
        samples = (
            {
                "nid": 4,
                "folder_path": "Inbox",
                "modification_time": None,
                "subject": None,
            },
        )

    monkeypatch.setattr(cli, "inspect_pst", lambda *_args, **_kwargs: Report())

    result = CliRunner().invoke(cli.main, ["inspect", "archive.pst"])

    assert result.exit_code == 0
    assert "Throughput: 6.0 messages/second" in result.output
    assert "OSError: broken" in result.output
    assert "NID 4 in Inbox (None):" in result.output


def test_inspect_command_reports_reader_errors(monkeypatch):
    monkeypatch.setattr(
        cli,
        "inspect_pst",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("bad")),
    )

    result = CliRunner().invoke(cli.main, ["inspect", "archive.pst"])

    assert result.exit_code == 1
    assert "Error: bad" in result.output


def test_get_config_template(tmp_path):
    output_path = tmp_path / "config.yaml"
    result = CliRunner().invoke(cli.main, ["--get-config-template", output_path])

    assert result.exit_code == 0
    assert "log_level: INFO" in output_path.read_text()


def test_no_subcommand_shows_help_and_accepts_config_overrides():
    runner = CliRunner()
    no_command = runner.invoke(cli.main)
    overridden_config = runner.invoke(
        cli.main,
        [
            "--archive-pst-path",
            "archive.pst",
            "--archive-index-path",
            "index.sqlite",
        ],
    )

    assert no_command.exit_code == 0
    assert "Usage:" in no_command.output
    assert overridden_config.exit_code == 0
    assert "compare-snapshots" in overridden_config.output


def test_snapshot_command_writes_metadata(monkeypatch):
    class Report:
        message_count = 3
        scan_errors = ()
        snapshot = object()

    written = []
    monkeypatch.setattr(cli, "inspect_pst", lambda *_args, **_kwargs: Report())
    monkeypatch.setattr(
        cli, "write_snapshot", lambda snapshot, path: written.append((snapshot, path))
    )

    result = CliRunner().invoke(cli.main, ["snapshot", "archive.pst", "snapshot.json"])

    assert result.exit_code == 0
    assert written == [(Report.snapshot, "snapshot.json")]
    assert "Wrote snapshot with 3 messages" in result.output


def test_snapshot_command_reports_write_errors(monkeypatch):
    class Report:
        message_count = 3
        scan_errors = ()
        snapshot = object()

    def raise_write_error(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(cli, "inspect_pst", lambda *_args, **_kwargs: Report())
    monkeypatch.setattr(cli, "write_snapshot", raise_write_error)

    result = CliRunner().invoke(cli.main, ["snapshot", "archive.pst", "snapshot.json"])

    assert result.exit_code == 1
    assert "Error: disk full" in result.output


def test_snapshot_command_refuses_incomplete_traversal_without_writing(
    monkeypatch, tmp_path
):
    class Report:
        message_count = 2
        scan_errors = ("OSError: bad item",)
        snapshot = object()

    output = tmp_path / "snapshot.json"
    monkeypatch.setattr(cli, "inspect_pst", lambda *_args, **_kwargs: Report())

    result = CliRunner().invoke(
        cli.main, ["snapshot", "archive.pst", str(output), "--json"]
    )

    assert result.exit_code == 1
    assert not output.exists()
    assert json.loads(result.output) == {
        "error": {
            "code": "incomplete_traversal",
            "message": (
                "Snapshot not written because PST traversal was incomplete: "
                "OSError: bad item"
            ),
        }
    }


def test_compare_snapshots_command_outputs_json_and_human_summary(
    monkeypatch, tmp_path
):
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.touch()
    after.touch()
    comparison = {
        "new": [],
        "missing": [1],
        "modified": [],
        "moved": [],
        "unchanged": {"count": 1},
        "suspicious_identity": {"store_uid_changed": False},
    }
    monkeypatch.setattr(cli, "read_snapshot", lambda path: path)
    monkeypatch.setattr(cli, "compare_snapshots", lambda *_: comparison)

    runner = CliRunner()
    json_result = runner.invoke(
        cli.main, ["compare-snapshots", str(before), str(after), "--json"]
    )
    human_result = runner.invoke(
        cli.main, ["compare-snapshots", str(before), str(after)]
    )

    assert json.loads(json_result.output) == comparison
    assert human_result.output == (
        "new: 0\n"
        "missing: 1\n"
        "modified: 0\n"
        "moved: 0\n"
        "unchanged: 1\n"
        "store UID changed: False\n"
    )


def test_compare_snapshots_command_reports_invalid_snapshots(monkeypatch, tmp_path):
    path = tmp_path / "snapshot.json"
    path.touch()
    monkeypatch.setattr(
        cli,
        "read_snapshot",
        lambda _: (_ for _ in ()).throw(cli.SnapshotFormatError("bad")),
    )

    result = CliRunner().invoke(cli.main, ["compare-snapshots", str(path), str(path)])

    assert result.exit_code == 1
    assert "Error: bad" in result.output


def test_configuration_error_is_reported(monkeypatch):
    class InvalidConfigManager:
        def __init__(self, *args, **kwargs):
            pass

        def config_from_env_vars(self):
            pass

        def config_from_cli_args(self, args):
            pass

        def validate(self):
            raise ConfigValidationError("invalid config")

    monkeypatch.setattr(cli, "ConfigManager", InvalidConfigManager)
    result = CliRunner().invoke(cli.main)

    assert result.exit_code == 1
    assert result.output == "Error: invalid config\n"


def _archive_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "archive:\n  pst_path: archive.pst\n  index_path: index.sqlite\n"
    )
    return config_path


def test_status_command_outputs_configured_index_metadata_as_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report = {
        "fresh": True,
        "index_exists": True,
        "index_path": "index.sqlite",
        "last_successful_sync": "2026-08-20T12:30:00+00:00",
        "schema_version": 2,
        "source_error": None,
        "source_mtime_ns": 2,
        "source_path": "archive.pst",
        "source_size": 1,
        "store_uid": "store",
    }
    monkeypatch.setattr(cli, "index_status", lambda *_: report)

    result = CliRunner().invoke(
        cli.main, ["--config", str(_archive_config(tmp_path)), "status", "--json"]
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == report


def test_search_command_synchronizes_and_returns_lightweight_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synchronized: list[tuple[str, str]] = []
    monkeypatch.setattr(cli, "sync_pst", lambda *paths: synchronized.append(paths))
    monkeypatch.setattr(
        cli,
        "search_messages",
        lambda *args, **kwargs: [
            SearchResult(
                id="store:3",
                date="2026-08-20T12:30:00",
                sender="Sender",
                recipients=("recipient@example.test",),
                subject="Status update",
                folder="Root/Inbox",
                snippet="Capon calibration",
                score=1.5,
            )
        ],
    )

    result = CliRunner().invoke(
        cli.main,
        [
            "--config",
            str(_archive_config(tmp_path)),
            "search",
            "Capon",
            "--from",
            "Sender",
            "--to",
            "recipient@example.test",
            "--after",
            "2026-08-01",
            "--before",
            "2026-09-01",
            "--folder",
            "Root/Inbox",
            "--has-attachment",
            "--limit",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0
    assert synchronized == [("archive.pst", "index.sqlite", cli.HistorySettings())]
    assert json.loads(result.output) == [
        {
            "date": "2026-08-20T12:30:00",
            "folder": "Root/Inbox",
            "from": "Sender",
            "id": "store:3",
            "score": 1.5,
            "snippet": "Capon calibration",
            "subject": "Status update",
            "to": ["recipient@example.test"],
        }
    ]


def test_search_command_accepts_filter_only_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(cli, "sync_pst", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "search_messages",
        lambda *args, **kwargs: calls.append(args) or [],
    )

    result = CliRunner().invoke(
        cli.main,
        ["--config", str(_archive_config(tmp_path)), "search", "--from", "Sender"],
    )

    assert result.exit_code == 0
    assert calls[0][1] is None


def test_search_command_passes_offset_and_rejects_negative_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(cli, "sync_pst", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "search_messages",
        lambda *_args, **kwargs: calls.append(kwargs) or [],
    )
    config = ["--config", str(_archive_config(tmp_path)), "search", "Capon"]
    runner = CliRunner()

    page = runner.invoke(cli.main, [*config, "--limit", "2", "--offset", "2"])
    invalid = runner.invoke(cli.main, [*config, "--offset", "-1", "--json"])

    assert page.exit_code == 0
    assert calls[0]["limit"] == 2
    assert calls[0]["offset"] == 2
    assert invalid.exit_code == 2
    assert json.loads(invalid.output)["error"]["code"] == "invalid_request"


def test_search_command_rejects_requests_without_query_or_filters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synchronized: list[tuple[object, ...]] = []
    monkeypatch.setattr(cli, "sync_pst", lambda *args: synchronized.append(args))

    result = CliRunner().invoke(
        cli.main,
        ["--config", str(_archive_config(tmp_path)), "search", "--json"],
    )

    assert result.exit_code == 1
    assert json.loads(result.output) == {
        "error": {
            "code": "invalid_request",
            "message": "Search requires QUERY or at least one structured filter.",
        }
    }
    assert synchronized == []


def test_search_passes_owner_history_settings_to_synchronization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "archive:\n  pst_path: archive.pst\n  index_path: index.sqlite\n"
        "history:\n  owner_emails:\n    - owner@example.test\n"
        "  owner_names:\n    - Owner\n  timezone: Europe/Prague\n"
    )
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(cli, "sync_pst", lambda *args: calls.append(args))
    monkeypatch.setattr(cli, "search_messages", lambda *_args, **_kwargs: [])

    result = CliRunner().invoke(cli.main, ["--config", str(config_path), "search", "x"])

    assert result.exit_code == 0
    assert calls == [
        (
            "archive.pst",
            "index.sqlite",
            cli.HistorySettings(("owner@example.test",), ("Owner",), "Europe/Prague"),
        )
    ]


def test_search_from_owner_expands_aliases_and_validates_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "archive:\n  pst_path: archive.pst\n  index_path: index.sqlite\n"
        "history:\n  owner_emails:\n    - owner@example.test\n"
        "  owner_names:\n    - Owner\n  timezone: UTC\n"
    )
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(cli, "sync_pst", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "search_messages",
        lambda *_args, **kwargs: calls.append(kwargs) or [],
    )
    runner = CliRunner()

    result = runner.invoke(
        cli.main, ["--config", str(config_path), "search", "--from-owner"]
    )
    conflict = runner.invoke(
        cli.main,
        [
            "--config",
            str(config_path),
            "search",
            "x",
            "--from",
            "Owner",
            "--from-owner",
        ],
    )
    missing = runner.invoke(
        cli.main,
        ["--config", str(_archive_config(tmp_path)), "search", "x", "--from-owner"],
    )

    assert result.exit_code == 0
    assert calls[0]["sender_aliases"] == ("owner@example.test", "Owner")
    assert conflict.exit_code == 1
    assert "cannot be combined" in conflict.output
    assert missing.exit_code == 1
    assert "requires configured" in missing.output


def test_show_command_reads_only_the_persisted_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "get_message",
        lambda *_, **__: {
            "body": "Complete body",
            "id": "store:3",
            "subject": "Status",
        },
    )
    monkeypatch.setattr(
        cli,
        "sync_pst",
        lambda *_: (_ for _ in ()).throw(AssertionError("show must not synchronize")),
    )

    result = CliRunner().invoke(
        cli.main,
        ["--config", str(_archive_config(tmp_path)), "show", "store:3", "--json"],
    )

    assert result.exit_code == 0
    assert json.loads(result.output) == {
        "body": "Complete body",
        "id": "store:3",
        "subject": "Status",
    }


def test_show_command_selects_cleaned_or_source_body_for_all_output_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def get_cleaned_message(*_: object) -> dict[str, object]:
        calls.append("clean")
        return {
            "attachment_count": 0,
            "body": "Clean body",
            "date": None,
            "folder": "Root/Inbox",
            "from": None,
            "id": "store:3",
            "subject": "Status",
            "to": [],
        }

    def get_source_message(*_: object) -> dict[str, object]:
        calls.append("source")
        return {
            "attachment_count": 0,
            "body": "Source body",
            "date": None,
            "folder": "Root/Inbox",
            "from": None,
            "id": "store:3",
            "subject": "Status",
            "to": [],
        }

    monkeypatch.setattr(cli, "get_message", get_cleaned_message)
    monkeypatch.setattr(cli, "get_full_message", get_source_message)
    config = ["--config", str(_archive_config(tmp_path)), "show", "store:3"]
    runner = CliRunner()

    cleaned_json = runner.invoke(cli.main, [*config, "--json"])
    full_json = runner.invoke(cli.main, [*config, "--full", "--json"])
    cleaned_text = runner.invoke(cli.main, config)
    full_text = runner.invoke(cli.main, [*config, "--full"])

    assert json.loads(cleaned_json.output)["body"] == "Clean body"
    assert json.loads(full_json.output)["body"] == "Source body"
    assert cleaned_text.output.endswith("Clean body\n")
    assert full_text.output.endswith("Source body\n")
    assert calls == ["clean", "source", "clean", "source"]


def test_thread_command_reads_only_the_persisted_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = {
        "id": "store:3",
        "messages": [
            {
                "body": "First contribution",
                "date": "2026-08-20T12:00:00",
                "folder": "Root/Inbox",
                "from": "First sender",
                "id": "store:2",
                "subject": "Status",
                "to": ["recipient@example.test"],
            },
            {
                "body": "Second contribution",
                "date": "2026-08-20T12:30:00",
                "folder": "Root/Inbox",
                "from": "Second sender",
                "id": "store:3",
                "subject": "Re: Status",
                "to": [],
            },
        ],
    }
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(cli, "get_thread", lambda *args: calls.append(args) or value)
    monkeypatch.setattr(
        cli,
        "sync_pst",
        lambda *_: (_ for _ in ()).throw(AssertionError("thread must not synchronize")),
    )
    config = ["--config", str(_archive_config(tmp_path)), "thread", "store:3"]
    runner = CliRunner()

    json_result = runner.invoke(cli.main, [*config, "--json"])
    text_result = runner.invoke(cli.main, config)

    assert json_result.exit_code == 0
    assert json.loads(json_result.output) == value
    assert text_result.exit_code == 0
    assert "Message 1: store:2" in text_result.output
    assert "First contribution" in text_result.output
    assert "---" in text_result.output
    assert "Message 2: store:3" in text_result.output
    assert calls == [("index.sqlite", "store:3"), ("index.sqlite", "store:3")]


def test_thread_command_reports_index_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "get_thread",
        lambda *_: (_ for _ in ()).throw(ValueError("Message not found: store:3")),
    )

    result = CliRunner().invoke(
        cli.main,
        ["--config", str(_archive_config(tmp_path)), "thread", "store:3"],
    )

    assert result.exit_code == 1
    assert "Error: Message not found: store:3" in result.output


def test_attachment_commands_list_metadata_and_extract_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    values = [
        {
            "filename": "anonymous-image.png",
            "id": "store:3:0",
            "mime_type": "image/png",
            "size": 20,
        }
    ]
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(cli, "list_attachments", lambda *_: values)

    def extract(
        source: str,
        database: str,
        attachment_id: str,
        output: str,
        history: cli.HistorySettings,
    ) -> int:
        calls.append((source, database, attachment_id, output, history))
        return 20

    monkeypatch.setattr(cli, "extract_attachment", extract)
    config = ["--config", str(_archive_config(tmp_path))]
    runner = CliRunner()

    listed = runner.invoke(cli.main, [*config, "attachments", "store:3"])
    listed_json = runner.invoke(cli.main, [*config, "attachments", "store:3", "--json"])
    extracted = runner.invoke(
        cli.main,
        [*config, "attachment", "store:3:0", "--output", "image.png"],
    )

    assert listed.output == "store:3:0  anonymous-image.png  image/png  20\n"
    assert json.loads(listed_json.output) == values
    assert extracted.output == "Wrote 20 bytes to image.png\n"
    assert calls == [
        ("archive.pst", "index.sqlite", "store:3:0", "image.png", cli.HistorySettings())
    ]


def test_attachment_passes_owner_history_settings_to_synchronization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "archive:\n  pst_path: archive.pst\n  index_path: index.sqlite\n"
        "history:\n  owner_names:\n    - Owner\n  timezone: Europe/Prague\n"
    )
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        cli, "extract_attachment", lambda *args: calls.append(args) or 20
    )

    result = CliRunner().invoke(
        cli.main,
        [
            "--config",
            str(config_path),
            "attachment",
            "store:3:0",
            "--output",
            "image.png",
        ],
    )

    assert result.exit_code == 0
    assert calls == [
        (
            "archive.pst",
            "index.sqlite",
            "store:3:0",
            "image.png",
            cli.HistorySettings((), ("Owner",), "Europe/Prague"),
        )
    ]


def test_history_settings_reject_invalid_values() -> None:
    context = type(
        "Context",
        (),
        {"obj": {"history": {"owner_emails": "owner@example.test"}}},
    )()

    with pytest.raises(cli.CliContractError, match="Invalid history"):
        cli._history_settings(context)

    context.obj = {
        "history": {"owner_emails": [], "owner_names": [], "timezone": "nope"}
    }
    with pytest.raises(cli.CliContractError, match="not an IANA"):
        cli._history_settings(context)


def test_attachment_commands_report_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ["--config", str(_archive_config(tmp_path))]
    monkeypatch.setattr(
        cli,
        "list_attachments",
        lambda *_: (_ for _ in ()).throw(ValueError("missing attachment")),
    )
    listed = CliRunner().invoke(cli.main, [*config, "attachments", "store:3"])
    monkeypatch.setattr(
        cli,
        "extract_attachment",
        lambda *_: (_ for _ in ()).throw(OSError("write failed")),
    )
    extracted = CliRunner().invoke(
        cli.main,
        [*config, "attachment", "store:3:0", "--output", "image.png"],
    )

    assert listed.exit_code == 1
    assert "missing attachment" in listed.output
    assert extracted.exit_code == 1
    assert "write failed" in extracted.output


def test_attachment_command_rejects_existing_output_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def extract(*_: object) -> int:
        raise FileExistsError("image.png")

    monkeypatch.setattr(cli, "extract_attachment", extract)
    config = ["--config", str(_archive_config(tmp_path))]
    runner = CliRunner()

    text_result = runner.invoke(
        cli.main,
        [*config, "attachment", "store:3:0", "--output", "image.png"],
    )
    json_result = runner.invoke(
        cli.main,
        [*config, "attachment", "store:3:0", "--output", "image.png", "--json"],
    )

    message = "Output path already exists and will not be overwritten: image.png"
    assert text_result.exit_code == 1
    assert text_result.output == f"Error: {message}\n"
    assert json_result.exit_code == 1
    assert json.loads(json_result.output) == {
        "error": {"code": "output_exists", "message": message}
    }


def test_agent_commands_have_human_readable_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "index_status",
        lambda *_: {
            "fresh": False,
            "index_exists": True,
            "index_path": "index.sqlite",
            "last_successful_sync": None,
            "schema_version": 2,
            "source_error": "missing PST",
            "source_mtime_ns": None,
            "source_path": "archive.pst",
            "source_size": None,
            "store_uid": "store",
        },
    )
    monkeypatch.setattr(
        cli,
        "list_folders",
        lambda *_: [{"id": "store:2", "path": "Root/Inbox"}],
    )
    monkeypatch.setattr(cli, "sync_pst", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "search_messages",
        lambda *_args, **_kwargs: [
            SearchResult(
                id="store:3",
                date=None,
                sender=None,
                recipients=(),
                subject=None,
                folder="Root/Inbox",
                snippet="Capon",
                score=1.5,
            )
        ],
    )
    monkeypatch.setattr(
        cli,
        "get_message",
        lambda *_, **__: {
            "attachment_count": 0,
            "body": "Complete body",
            "date": None,
            "folder": "Root/Inbox",
            "from": None,
            "id": "store:3",
            "subject": "Status",
            "to": [],
        },
    )
    config = ["--config", str(_archive_config(tmp_path))]
    runner = CliRunner()

    status = runner.invoke(cli.main, [*config, "status"])
    folders = runner.invoke(cli.main, [*config, "folders"])
    folders_json = runner.invoke(cli.main, [*config, "folders", "--json"])
    search = runner.invoke(cli.main, [*config, "search", "Capon"])
    show = runner.invoke(cli.main, [*config, "show", "store:3"])

    assert "Source error: missing PST" in status.output
    assert folders.output == "store:2  Root/Inbox\n"
    assert json.loads(folders_json.output) == [{"id": "store:2", "path": "Root/Inbox"}]
    assert "store:3" in search.output
    assert "Capon" in search.output
    assert "Attachments: 0" in show.output
    assert show.output.endswith("Complete body\n")


def test_agent_commands_report_cache_and_search_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ["--config", str(_archive_config(tmp_path))]
    monkeypatch.setattr(
        cli,
        "list_folders",
        lambda *_: (_ for _ in ()).throw(ValueError("missing cache")),
    )
    folders = CliRunner().invoke(cli.main, [*config, "folders"])
    monkeypatch.setattr(cli, "sync_pst", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "search_messages",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad query")),
    )
    search = CliRunner().invoke(cli.main, [*config, "search", "bad"])
    monkeypatch.setattr(
        cli,
        "get_message",
        lambda *_, **__: (_ for _ in ()).throw(ValueError("missing message")),
    )
    show = CliRunner().invoke(cli.main, [*config, "show", "store:3"])
    missing_config = CliRunner().invoke(cli.main, ["status"])

    assert folders.exit_code == 1
    assert "Error: missing cache" in folders.output
    assert search.exit_code == 1
    assert "Error: bad query" in search.output
    assert show.exit_code == 1
    assert "Error: missing message" in show.output
    assert missing_config.exit_code == 1
    assert "Configure archive.pst_path" in missing_config.output


def test_json_errors_have_a_stable_envelope_and_no_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = ["--config", str(_archive_config(tmp_path))]
    monkeypatch.setattr(cli, "sync_pst", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "search_messages",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad query")),
    )
    runner = CliRunner()

    runtime_error = runner.invoke(cli.main, [*config, "search", "bad", "--json"])
    invalid_limit = runner.invoke(
        cli.main, [*config, "search", "valid", "--limit", "101", "--json"]
    )
    missing_config = runner.invoke(cli.main, ["status", "--json"])
    monkeypatch.setattr(
        cli,
        "sync_pst",
        lambda *_: (_ for _ in ()).throw(cli.PstSynchronizationError("changed PST")),
    )
    synchronization_error = runner.invoke(
        cli.main,
        [*config, "search", "valid", "--json"],
        standalone_mode=False,
    )

    assert runtime_error.exit_code == 1
    assert json.loads(runtime_error.output) == {
        "error": {"code": "invalid_request", "message": "bad query"}
    }
    assert invalid_limit.exit_code == 2
    assert json.loads(invalid_limit.output)["error"]["code"] == "invalid_request"
    assert missing_config.exit_code == 1
    assert json.loads(missing_config.output) == {
        "error": {
            "code": "configuration_error",
            "message": (
                "Configure archive.pst_path and archive.index_path before using "
                "this command."
            ),
        }
    }
    assert synchronization_error.exit_code == 1
    assert json.loads(synchronization_error.output) == {
        "error": {"code": "synchronization_error", "message": "changed PST"}
    }
    assert "Traceback" not in runtime_error.output


def test_json_like_query_value_does_not_select_json_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "sync_pst", lambda *_: None)
    monkeypatch.setattr(
        cli,
        "search_messages",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad query")),
    )

    result = CliRunner().invoke(
        cli.main,
        ["--config", str(_archive_config(tmp_path)), "search", "--", "--json"],
    )

    assert result.exit_code == 1
    assert result.output == "Error: bad query\n"
