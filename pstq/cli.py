"""Command-line interface for PST metadata diagnostics."""

from __future__ import annotations

import json
import sys
from importlib.resources import files
from typing import Any, cast

import click
from onacol import ConfigManager, ConfigValidationError  # type: ignore[import-untyped]

from pstq.metadata import (
    SnapshotFormatError,
    compare_snapshots,
    inspect_pst,
    read_snapshot,
    write_snapshot,
)
from pstq.pst import PstReaderError

DEFAULT_CONFIG_FILE = str(files("pstq").joinpath("default_config.yaml"))


@click.group(invoke_without_command=True)
@click.option(
    "--config",
    type=click.Path(exists=True),
    default=None,
    help="Path to the configuration file.",
)
@click.option(
    "--get-config-template",
    type=click.File("w"),
    default=None,
    help="Write default configuration template to the file.",
)
@click.pass_context
def main(ctx: click.Context, config: str | None, get_config_template: Any) -> None:
    """Inspect PST metadata and compare snapshots."""
    config_manager = ConfigManager(
        DEFAULT_CONFIG_FILE,
        env_var_prefix="pstq",
        optional_files=[config] if config else [],
    )
    if get_config_template:
        config_manager.generate_config_example(get_config_template)
        ctx.exit()

    config_manager.config_from_env_vars()
    config_manager.config_from_cli_args(ctx.args)
    try:
        config_manager.validate()
    except ConfigValidationError as error:
        click.secho("<----------------Configuration problem---------------->", fg="red")
        click.secho(str(error), fg="red", err=True)
        sys.exit(1)


@main.command()
@click.argument("path", type=click.Path(path_type=str))
@click.option(
    "--sample-size", type=click.IntRange(min=0), default=10, show_default=True
)
@click.option("--json", "json_output", is_flag=True, help="Print deterministic JSON.")
def inspect(path: str, sample_size: int, json_output: bool) -> None:
    """Report metadata traversal performance for PATH."""
    try:
        report = inspect_pst(path, sample_size=sample_size)
    except (OSError, PstReaderError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    if json_output:
        click.echo(_json(report.as_dict()), nl=False)
        return

    click.echo(f"libpff version: {report.libpff_version}")
    click.echo(f"PST size: {report.pst_size} bytes")
    click.echo(f"Store UID: {report.store_uid}")
    click.echo(f"Folders: {report.folder_count}")
    click.echo(f"Messages: {report.message_count}")
    click.echo(f"Duration: {report.duration_seconds:.3f} seconds")
    click.echo(f"Throughput: {report.messages_per_second or 0:.1f} messages/second")
    click.echo(f"Scan errors: {len(report.scan_errors)}")
    for scan_error in report.scan_errors:
        click.echo(f"  {scan_error}")
    click.echo("Sample messages:")
    for sample in report.samples:
        click.echo(
            "  "
            f"NID {sample['nid']} in {sample['folder_path']} "
            f"({sample['modification_time']}): {sample['subject'] or ''}"
        )


@main.command()
@click.argument("path", type=click.Path(path_type=str))
@click.argument("output", type=click.Path(path_type=str, dir_okay=False))
def snapshot(path: str, output: str) -> None:
    """Write a body-free metadata snapshot for PATH to OUTPUT."""
    try:
        report = inspect_pst(path, sample_size=0)
        write_snapshot(report.snapshot, output)
    except (OSError, PstReaderError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Wrote snapshot with {report.message_count} messages to {output}")


@main.command("compare-snapshots")
@click.argument("before", type=click.Path(exists=True, dir_okay=False, path_type=str))
@click.argument("after", type=click.Path(exists=True, dir_okay=False, path_type=str))
@click.option("--json", "json_output", is_flag=True, help="Print deterministic JSON.")
def compare_snapshots_command(before: str, after: str, json_output: bool) -> None:
    """Classify metadata changes between BEFORE and AFTER snapshots."""
    try:
        comparison = compare_snapshots(read_snapshot(before), read_snapshot(after))
    except SnapshotFormatError as error:
        raise click.ClickException(str(error)) from error
    if json_output:
        click.echo(_json(comparison), nl=False)
        return

    for category in ("new", "missing", "modified", "moved", "unchanged"):
        values = comparison[category]
        count = (
            len(values)
            if isinstance(values, list)
            else cast(dict[str, int], values)["count"]
        )
        click.echo(f"{category}: {count}")
    suspicious = cast(dict[str, object], comparison["suspicious_identity"])
    click.echo(f"store UID changed: {suspicious['store_uid_changed']}")


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":  # pragma: no cover
    main()
