"""Command line interface.

Currently one command: exporting the resource descriptor from a running application.

    querymate schema export app.main:app -o querymate.schema.json

The document is derived from the application - the models and the ``Exposed`` policy
already declared on each endpoint - so there is nothing to keep in sync by hand. Run it
in CI with ``--check`` to fail the build when the committed contract no longer matches
the code.
"""

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from querymate.core.descriptor import describe_app


def _load_app(target: str) -> Any:
    """Import ``module:attribute`` and return the attribute.

    Args:
        target: An import path such as ``app.main:app``.

    Raises:
        SystemExit: If the target cannot be imported or does not exist.
    """
    if ":" not in target:
        raise SystemExit(
            f"Expected 'module:attribute' (for example 'app.main:app'), got {target!r}."
        )
    module_name, attribute = target.split(":", 1)

    # The app usually lives in the working directory rather than on sys.path.
    sys.path.insert(0, str(Path.cwd()))
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise SystemExit(f"Could not import {module_name!r}: {exc}") from exc

    try:
        return getattr(module, attribute)
    except AttributeError as exc:
        raise SystemExit(
            f"Module {module_name!r} has no attribute {attribute!r}."
        ) from exc


def _render(document: dict[str, Any]) -> str:
    """Serialize deterministically, so regenerating produces an identical file."""
    return json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def export(args: argparse.Namespace) -> int:
    """Emit the descriptor, or compare it against a committed copy."""
    document = describe_app(_load_app(args.app))

    if not document["endpoints"]:
        print(
            "warning: no QueryMate endpoints found. Routes must use a dependency "
            "built with Querymate.for_model(...) to appear in the contract.",
            file=sys.stderr,
        )

    rendered = _render(document)

    if args.check:
        if args.output is None:
            raise SystemExit("--check needs -o/--output to know what to compare with.")
        existing = Path(args.output)
        if not existing.exists():
            print(
                f"{args.output} does not exist; run without --check.", file=sys.stderr
            )
            return 1
        if existing.read_text() != rendered:
            print(
                f"{args.output} is out of date. Regenerate it and commit the result.",
                file=sys.stderr,
            )
            return 1
        return 0

    if args.output:
        Path(args.output).write_text(rendered)
        resources = len(document["resources"])
        endpoints = len(document["endpoints"])
        print(
            f"Wrote {args.output} ({resources} resources, {endpoints} endpoints).",
            file=sys.stderr,
        )
    else:
        sys.stdout.write(rendered)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser."""
    parser = argparse.ArgumentParser(prog="querymate")
    subcommands = parser.add_subparsers(dest="command", required=True)

    schema = subcommands.add_parser("schema", help="Work with the resource descriptor.")
    schema_actions = schema.add_subparsers(dest="action", required=True)

    export_parser = schema_actions.add_parser(
        "export", help="Emit the resource descriptor for an application."
    )
    export_parser.add_argument("app", help="Import path, e.g. app.main:app")
    export_parser.add_argument(
        "-o", "--output", help="File to write. Defaults to stdout."
    )
    export_parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the output file is out of date. For CI.",
    )
    export_parser.set_defaults(handler=export)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = build_parser().parse_args(argv)
    handler: Any = args.handler
    return int(handler(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
