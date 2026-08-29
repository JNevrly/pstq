"""Command-line interface for PST metadata diagnostics."""

from __future__ import annotations

import json
import sys
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import click
from onacol import ConfigManager, ConfigValidationError  # type: ignore[import-untyped]

from pstq.index import (
    PstSynchronizationError,
    extract_attachment,
    get_message,
    index_status,
    list_attachments,
    list_folders,
    search_messages,
    sync_pst,
)
from pstq.metadata import (
    SnapshotFormatError,
    compare_snapshots,
    inspect_pst,
    read_snapshot,
    write_snapshot,
)
from pstq.pst import PstReaderError

DEFAULT_CONFIG_FILE = str(files("pstq").joinpath("default_config.yaml"))


@click.group(
    invoke_without_command=True,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
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
    ctx.obj = config_manager.config


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


@main.command()
@click.option("--json", "json_output", is_flag=True, help="Print deterministic JSON.")
@click.pass_context
def status(ctx: click.Context, json_output: bool) -> None:
    """Report configured source and SQLite index freshness."""
    source_path, database_path = _configured_paths(ctx)
    report = index_status(source_path, database_path)
    if json_output:
        click.echo(_json(report), nl=False)
        return
    for label, key in (
        ("Fresh", "fresh"),
        ("Source", "source_path"),
        ("Source size", "source_size"),
        ("Source mtime ns", "source_mtime_ns"),
        ("Index", "index_path"),
        ("Index exists", "index_exists"),
        ("Store UID", "store_uid"),
        ("Schema version", "schema_version"),
        ("Last successful sync", "last_successful_sync"),
    ):
        click.echo(f"{label}: {report[key]}")
    if report["source_error"]:
        click.echo(f"Source error: {report['source_error']}")


@main.command()
@click.option("--json", "json_output", is_flag=True, help="Print deterministic JSON.")
@click.pass_context
def folders(ctx: click.Context, json_output: bool) -> None:
    """List indexed folders with stable IDs and paths."""
    _, database_path = _configured_paths(ctx)
    try:
        values = list_folders(database_path)
    except (OSError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    if json_output:
        click.echo(_json(values), nl=False)
        return
    for value in values:
        click.echo(f"{value['id']}  {value['path']}")


@main.command()
@click.argument("query")
@click.option("--from", "sender", help="Match the sender name.")
@click.option("--to", "recipient", help="Match persisted recipient name or email.")
@click.option("--after", help="Include messages on or after this ISO-8601 timestamp.")
@click.option("--before", help="Include messages before this ISO-8601 timestamp.")
@click.option("--folder", help="Match an exact indexed folder path.")
@click.option("--has-attachment", is_flag=True, help="Require one or more attachments.")
@click.option(
    "--limit",
    type=click.IntRange(1, 100),
    default=20,
    show_default=True,
    help="Maximum results.",
)
@click.option("--json", "json_output", is_flag=True, help="Print deterministic JSON.")
@click.pass_context
def search(
    ctx: click.Context,
    query: str,
    sender: str | None,
    recipient: str | None,
    after: str | None,
    before: str | None,
    folder: str | None,
    has_attachment: bool,
    limit: int,
    json_output: bool,
) -> None:
    """Synchronize when needed, then search indexed message text."""
    source_path, database_path = _configured_paths(ctx)
    try:
        sync_pst(source_path, database_path)
        values = search_messages(
            database_path,
            query,
            sender=sender,
            recipient=recipient,
            after=after,
            before=before,
            folder=folder,
            has_attachment=has_attachment,
            limit=limit,
        )
    except (OSError, PstReaderError, PstSynchronizationError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    if json_output:
        click.echo(_json([value.as_dict() for value in values]), nl=False)
        return
    for value in values:
        click.echo(
            f"{value.id}  {value.date or ''}  {value.sender or ''}  "
            f"{value.subject or ''}\n  {value.folder}  {value.snippet}\n"
        )


@main.command()
@click.argument("message_id")
@click.option(
    "--full",
    "full_body",
    is_flag=True,
    help="Show the original raw body instead of cleaned content.",
)
@click.option("--json", "json_output", is_flag=True, help="Print deterministic JSON.")
@click.pass_context
def show(
    ctx: click.Context, message_id: str, full_body: bool, json_output: bool
) -> None:
    """Display one persisted message with cleaned content by default."""
    _, database_path = _configured_paths(ctx)
    try:
        message = get_message(database_path, message_id, full=full_body)
    except (OSError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    if json_output:
        click.echo(_json(message), nl=False)
        return
    for label, key in (
        ("ID", "id"),
        ("Date", "date"),
        ("From", "from"),
        ("To", "to"),
        ("Subject", "subject"),
        ("Folder", "folder"),
        ("Attachments", "attachment_count"),
    ):
        click.echo(f"{label}: {message[key]}")
    click.echo()
    click.echo(cast(str | None, message["body"]) or "")


@main.command()
@click.argument("message_id")
@click.option("--json", "json_output", is_flag=True, help="Print deterministic JSON.")
@click.pass_context
def attachments(ctx: click.Context, message_id: str, json_output: bool) -> None:
    """List persisted attachment metadata without opening the PST."""
    _, database_path = _configured_paths(ctx)
    try:
        values = list_attachments(database_path, message_id)
    except (OSError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    if json_output:
        click.echo(_json(values), nl=False)
        return
    for value in values:
        click.echo(
            f"{value['id']}  {value['filename'] or ''}  "
            f"{value['mime_type'] or ''}  {value['size'] or 0}"
        )


@main.command()
@click.argument("attachment_id")
@click.option(
    "--output",
    required=True,
    type=click.Path(dir_okay=False, path_type=str),
    help="New file path for the original attachment bytes.",
)
@click.pass_context
def attachment(ctx: click.Context, attachment_id: str, output: str) -> None:
    """Write original attachment bytes through a cached PST locator."""
    source_path, database_path = _configured_paths(ctx)
    try:
        written = extract_attachment(source_path, database_path, attachment_id, output)
    except (OSError, PstReaderError, PstSynchronizationError, ValueError) as error:
        raise click.ClickException(str(error)) from error
    click.echo(f"Wrote {written} bytes to {output}")


def _configured_paths(ctx: click.Context) -> tuple[str, str]:
    config = cast(dict[str, object], ctx.obj)
    archive = cast(dict[str, object], config.get("archive", {}))
    source_path = archive.get("pst_path")
    database_path = archive.get("index_path")
    if not isinstance(source_path, str) or not isinstance(database_path, str):
        raise click.ClickException(
            "Configure archive.pst_path and archive.index_path before using "
            "this command."
        )
    return str(Path(source_path)), str(Path(database_path))


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":  # pragma: no cover
    main()
