#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for the package and CLI."""

import json

import pytest
from click.testing import CliRunner
from onacol import ConfigValidationError

from pstq import cli, pstq


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
    """The CLI exposes PST metadata commands."""
    runner = CliRunner()
    result = runner.invoke(cli.main, ["--help"])
    assert result.exit_code == 0
    assert "compare-snapshots" in result.output
    assert "inspect" in result.output
    assert "snapshot" in result.output


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


def test_snapshot_command_writes_metadata(monkeypatch):
    class Report:
        message_count = 3
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
        snapshot = object()

    def raise_write_error(*_: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(cli, "inspect_pst", lambda *_args, **_kwargs: Report())
    monkeypatch.setattr(cli, "write_snapshot", raise_write_error)

    result = CliRunner().invoke(cli.main, ["snapshot", "archive.pst", "snapshot.json"])

    assert result.exit_code == 1
    assert "Error: disk full" in result.output


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
    assert "Configuration problem" in result.output
    assert "invalid config" in result.output
