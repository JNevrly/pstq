#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Tests for `pstq` package."""

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
    """Test the CLI."""
    runner = CliRunner()
    result = runner.invoke(cli.main)
    assert result.exit_code == 0
    assert "pstq.cli.main" in result.output
    help_result = runner.invoke(cli.main, ["--help"])
    assert help_result.exit_code == 0
    assert "Show this message and exit." in help_result.output


def test_get_config_template(tmp_path):
    output_path = tmp_path / "config.yaml"
    result = CliRunner().invoke(cli.main, ["--get-config-template", output_path])

    assert result.exit_code == 0
    assert "log_level: INFO" in output_path.read_text()


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
