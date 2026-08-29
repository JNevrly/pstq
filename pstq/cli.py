"""Command-line interface for PST metadata diagnostics."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import click
from onacol import ConfigManager, ConfigValidationError  # type: ignore[import-untyped]

from pstq.index import (
    DEFAULT_HISTORY_SETTINGS,
    HistorySettings,
    PstSynchronizationError,
    extract_attachment,
    get_message,
    get_thread,
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


class CliContractError(click.ClickException):
    """A predictable failure with an agent-facing error code."""

    def __init__(self, message: str, code: str = "command_failed") -> None:
        super().__init__(message)
        self.code = code


class CliContractGroup(click.Group):
    """Render every expected command failure in the selected output format."""

    def main(
        self,
        args: Sequence[str] | None = None,
        prog_name: str | None = None,
        complete_var: str | None = None,
        standalone_mode: bool = True,
        **extra: Any,
    ) -> Any:
        requested_args = sys.argv[1:] if args is None else args
        try:
            return super().main(
                args=args,
                prog_name=prog_name,
                complete_var=complete_var,
                standalone_mode=False,
                **extra,
            )
        except click.ClickException as error:
            if _json_requested(requested_args):
                click.echo(
                    _json(
                        {
                            "error": {
                                "code": getattr(error, "code", "invalid_request"),
                                "message": error.format_message(),
                            }
                        }
                    ),
                    err=True,
                    nl=False,
                )
            else:
                error.show()
            if standalone_mode:
                raise SystemExit(error.exit_code) from error
            raise click.exceptions.Exit(error.exit_code) from error


@click.group(
    cls=CliContractGroup,
    invoke_without_command=True,
    context_settings={
        "allow_extra_args": True,
        "help_option_names": ["-h", "--help"],
        "ignore_unknown_options": True,
    },
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
    """Query one Outlook PST through a local, disposable SQLite cache.

    Configuration:
      Set archive.pst_path and archive.index_path in --config FILE, or set
      PSTQ_ARCHIVE__PST_PATH and PSTQ_ARCHIVE__INDEX_PATH. Optional history
      owner aliases and timezone provide context for quoted owner history.
      Exactly one PST and
      one SQLite cache are configured per invocation. The index directory must
      already exist: synchronization creates a sibling temporary database and
      atomically replaces the cache only after a successful source check.

    Agent contract:
      Use --json for deterministic, pretty-printed JSON with sorted keys.
      Message IDs are stable selectors; folder IDs are STORE_UID:NID; attachment
      IDs are STORE_UID:MESSAGE_NID:INDEX. Read each command's --help for its
      complete request, result schema, limits, and source/cache access behavior.
      Runtime failures in JSON mode are written to stderr as
      {"error":{"code":"...","message":"..."}}. Exit 0 means success,
      1 means an operational/configuration failure, and 2 means invalid CLI
      input. Stack traces are not emitted unless Python is explicitly asked to
      debug the process.

    Safety and synchronization:
      PST files are always opened read-only and are never modified. SQLite is a
      disposable cache, not a source of truth. search and attachment synchronize
      first when source path, size, mtime, schema, or cleaner version differs;
      status, folders, show, thread, and attachments read SQLite only. Do not
      run against a PST Outlook is modifying. libpff/pypff can fail on malformed
      or unsupported PST structures, and stock pypff has no direct item lookup;
      attachment extraction uses a cached, validated traversal locator instead.
    """
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
        raise CliContractError(str(error), "configuration_error") from error
    ctx.obj = config_manager.config


@main.command()
@click.argument("path", type=click.Path(path_type=str))
@click.option(
    "--sample-size", type=click.IntRange(min=0), default=10, show_default=True
)
@click.option("--json", "json_output", is_flag=True, help="Print deterministic JSON.")
def inspect(path: str, sample_size: int, json_output: bool) -> None:
    """Report read-only metadata traversal performance for PATH.

    This diagnostic bypasses the configured cache and opens PATH read-only. It
    does not request message bodies or attachment bytes. --sample-size defaults
    to 10 and may be zero. With --json, the object schema is
    {duration_seconds, folder_count, libpff_version, message_count,
    messages_per_second, pst_size, samples, scan_errors, store_uid}; samples
    contain nid, folder_path, modification_time, and subject.
    """
    try:
        report = inspect_pst(path, sample_size=sample_size)
    except (OSError, PstReaderError, ValueError) as error:
        raise _command_error(error) from error
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
    """Write a body-free metadata snapshot for PATH to OUTPUT.

    PATH is opened read-only. OUTPUT is JSON with format_version, store_uid,
    folders [{nid, path}], and messages [{nid, folder_nid, modification_time}].
    This diagnostic command writes OUTPUT and does not use archive.index_path.
    """
    try:
        report = inspect_pst(path, sample_size=0)
        write_snapshot(report.snapshot, output)
    except (OSError, PstReaderError, ValueError) as error:
        raise _command_error(error) from error
    click.echo(f"Wrote snapshot with {report.message_count} messages to {output}")


@main.command("compare-snapshots")
@click.argument("before", type=click.Path(exists=True, dir_okay=False, path_type=str))
@click.argument("after", type=click.Path(exists=True, dir_okay=False, path_type=str))
@click.option("--json", "json_output", is_flag=True, help="Print deterministic JSON.")
def compare_snapshots_command(before: str, after: str, json_output: bool) -> None:
    """Classify metadata changes between BEFORE and AFTER snapshots.

    Inputs must be snapshots made by snapshot. --json returns an object with
    new, missing, modified, moved, unchanged, and suspicious_identity. The
    first four are lists of metadata records; unchanged is a count summary;
    suspicious_identity reports whether the source store UID changed.
    """
    try:
        comparison = compare_snapshots(read_snapshot(before), read_snapshot(after))
    except SnapshotFormatError as error:
        raise _command_error(error) from error
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
    """Report configured source and SQLite cache freshness without opening PST.

    --json returns {cleaner_version, fresh, index_exists, index_path,
    last_successful_sync, schema_version, source_error, source_mtime_ns,
    source_path, source_size, store_uid}. fresh is true only when cache schema,
    cleaner version, and source path/size/mtime agree. This command never
    synchronizes and can report a missing or unreadable source in source_error.
    """
    source_path, database_path = _configured_paths(ctx)
    report = index_status(source_path, database_path, _history_settings(ctx))
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
    """List folders from the existing cache with stable IDs and paths.

    --json returns a path-ordered array of {id, name, parent_id, path}. id and
    parent_id use STORE_UID:NID; parent_id is null for the root. This command
    reads SQLite only and fails if no usable cache exists; run search first to
    create or refresh it.
    """
    _, database_path = _configured_paths(ctx)
    try:
        values = list_folders(database_path)
    except (OSError, ValueError) as error:
        raise _command_error(error) from error
    if json_output:
        click.echo(_json(values), nl=False)
        return
    for value in values:
        click.echo(f"{value['id']}  {value['path']}")


@main.command()
@click.argument("query")
@click.option("--from", "sender", help="Match the sender name.")
@click.option(
    "--from-owner",
    is_flag=True,
    help="Match any configured history.owner_emails or history.owner_names alias.",
)
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
    from_owner: bool,
    recipient: str | None,
    after: str | None,
    before: str | None,
    folder: str | None,
    has_attachment: bool,
    limit: int,
    json_output: bool,
) -> None:
    """Synchronize when needed, then run a bounded FTS5 search.

    QUERY uses SQLite FTS5 syntax and must not be empty. --from and --to match
    sender and persisted recipient text. --from-owner matches any configured
    owner alias and cannot be combined with --from. --after is inclusive and
    --before is exclusive ISO-8601 timestamp filtering; --folder is an exact
    cached path; --has-attachment requires attachment_count > 0. --limit
    defaults to 20 and accepts 1 through 100. search compares source path, size,
    and mtime before querying, then atomically synchronizes if the cache is stale.

    --json returns at most limit lightweight records, ordered by FTS score then
    stable message ID: [{date, folder, from, id, score, snippet, subject, to}].
    id is a stable selector for show, thread, and attachments. Bodies are
    intentionally omitted; call show only for relevant candidates.
    """
    source_path, database_path = _configured_paths(ctx)
    try:
        history = _history_settings(ctx)
        if from_owner and sender:
            raise CliContractError(
                "--from-owner cannot be combined with --from.", "invalid_request"
            )
        sender_aliases = (
            history.owner_emails + history.owner_names if from_owner else ()
        )
        if from_owner and not sender_aliases:
            raise CliContractError(
                "--from-owner requires configured history.owner_emails or "
                "history.owner_names.",
                "configuration_error",
            )
        if history == DEFAULT_HISTORY_SETTINGS:
            sync_pst(source_path, database_path)
        else:
            sync_pst(source_path, database_path, history)
        values = search_messages(
            database_path,
            query,
            sender=sender,
            sender_aliases=sender_aliases,
            recipient=recipient,
            after=after,
            before=before,
            folder=folder,
            has_attachment=has_attachment,
            limit=limit,
        )
    except (OSError, PstReaderError, PstSynchronizationError, ValueError) as error:
        raise _command_error(error) from error
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
    """Display one persisted message from SQLite; use --full for raw body.

    MESSAGE_ID must be a stable selector returned by search. The default body is
    conservatively cleaned of recognizable quoted history; --full selects the
    preserved raw body where available in both text and JSON output. This command
    does not open or synchronize the PST.

    --json returns {attachment_count, body, body_format, client_submit_time,
    conversation_index, conversation_topic, date, delivery_time, folder,
    folder_id, from, id, in_reply_to, internet_message_id, modification_time,
    references, subject, to, transport_headers}. Values may be null when the
    PST did not expose that property. id is a stable selector; folder_id is a
    stable STORE_UID:NID value.
    """
    _, database_path = _configured_paths(ctx)
    try:
        message = get_message(database_path, message_id, full=full_body)
    except (OSError, ValueError) as error:
        raise _command_error(error) from error
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
def thread(ctx: click.Context, message_id: str, json_output: bool) -> None:
    """Display related cached messages as separate contributions.

    MESSAGE_ID is a stable selector returned by search. --json returns
    {id, messages}, where id is the requested selector and messages is a
    chronological array of the same message schema returned by show (with the
    cleaned body). Relationships use persisted Internet headers and Outlook
    conversation metadata; absent or inconsistent metadata can leave a thread
    incomplete. This command reads SQLite only and does not open or synchronize
    the PST.
    """
    _, database_path = _configured_paths(ctx)
    try:
        result = get_thread(database_path, message_id)
    except (OSError, ValueError) as error:
        raise _command_error(error) from error
    if json_output:
        click.echo(_json(result), nl=False)
        return
    for position, message in enumerate(
        cast(list[dict[str, object]], result["messages"]), 1
    ):
        if position > 1:
            click.echo("\n---\n")
        click.echo(f"Message {position}: {message['id']}")
        for label, key in (
            ("Date", "date"),
            ("From", "from"),
            ("To", "to"),
            ("Subject", "subject"),
            ("Folder", "folder"),
        ):
            click.echo(f"{label}: {message[key]}")
        click.echo()
        click.echo(cast(str | None, message["body"]) or "")


@main.command()
@click.argument("message_id")
@click.option("--json", "json_output", is_flag=True, help="Print deterministic JSON.")
@click.pass_context
def attachments(ctx: click.Context, message_id: str, json_output: bool) -> None:
    """List persisted attachment metadata from SQLite without opening the PST.

    MESSAGE_ID is a stable selector returned by search. --json returns an
    index-ordered array of {attachment_method, content_id, content_location,
    filename, hidden, id, mime_type, rendering_position, size}. id is the stable
    STORE_UID:MESSAGE_NID:INDEX selector for attachment. Metadata fields may be
    null when unavailable. This command reads SQLite only and does not refresh.
    """
    _, database_path = _configured_paths(ctx)
    try:
        values = list_attachments(database_path, message_id)
    except (OSError, ValueError) as error:
        raise _command_error(error) from error
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
    """Write original attachment bytes through its cached PST traversal locator.

    ATTACHMENT_ID must be the STORE_UID:MESSAGE_NID:INDEX returned by
    attachments. --output is required and names a new output file; existing
    files may be replaced by the operating system. This command synchronizes if
    the source changed, validates that the cached locator still reaches the
    expected item, then opens the PST read-only to copy original bytes. It emits
    a human-readable byte count and has no JSON success mode.
    """
    source_path, database_path = _configured_paths(ctx)
    try:
        history = _history_settings(ctx)
        if history == DEFAULT_HISTORY_SETTINGS:
            written = extract_attachment(
                source_path, database_path, attachment_id, output
            )
        else:
            written = extract_attachment(
                source_path, database_path, attachment_id, output, history
            )
    except (OSError, PstReaderError, PstSynchronizationError, ValueError) as error:
        raise _command_error(error) from error
    click.echo(f"Wrote {written} bytes to {output}")


def _configured_paths(ctx: click.Context) -> tuple[str, str]:
    config = cast(dict[str, object], ctx.obj)
    archive = cast(dict[str, object], config.get("archive", {}))
    source_path = archive.get("pst_path")
    database_path = archive.get("index_path")
    if not isinstance(source_path, str) or not isinstance(database_path, str):
        raise CliContractError(
            "Configure archive.pst_path and archive.index_path before using "
            "this command.",
            "configuration_error",
        )
    return str(Path(source_path)), str(Path(database_path))


def _history_settings(ctx: click.Context) -> HistorySettings:
    config = cast(dict[str, object], ctx.obj)
    history = cast(dict[str, object], config.get("history", {}))
    emails = history.get("owner_emails", ())
    names = history.get("owner_names", ())
    timezone = history.get("timezone", "UTC")
    if (
        not isinstance(emails, list)
        or not all(isinstance(value, str) for value in emails)
        or not isinstance(names, list)
        or not all(isinstance(value, str) for value in names)
        or not isinstance(timezone, str)
    ):
        raise CliContractError("Invalid history configuration.", "configuration_error")
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise CliContractError(
            f"history.timezone is not an IANA timezone: {timezone}",
            "configuration_error",
        ) from error
    return HistorySettings(tuple(emails), tuple(names), timezone)


def _json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _command_error(error: Exception) -> CliContractError:
    if isinstance(error, PstSynchronizationError):
        return CliContractError(str(error), "synchronization_error")
    if isinstance(error, (OSError, PstReaderError)):
        return CliContractError(str(error), "source_error")
    return CliContractError(str(error), "invalid_request")


def _json_requested(args: Sequence[str] | None) -> bool:
    return args is not None and "--json" in args


if __name__ == "__main__":  # pragma: no cover
    main()
