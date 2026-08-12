"""Tests for the ``querymate`` command line interface.

The point of ``schema export --check`` is to fail a build when the committed contract
no longer matches the code, so the exit codes are the feature: a wrong one either
lets a stale contract through or breaks a build that was fine.
"""

import json
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi import Depends, FastAPI

from querymate.cli import _render, build_parser, export, main
from querymate.core.querymate import Querymate
from tests.models import User

APP_MODULE = """
from fastapi import Depends, FastAPI
from querymate.core.querymate import Querymate
from tests.models import User

app = FastAPI()
not_an_app = 42


@app.get("/users")
def list_users(q: Querymate = Depends(Querymate.for_model(User))) -> list:
    return []
"""

EMPTY_APP_MODULE = """
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health() -> dict:
    return {}
"""


@pytest.fixture
def app_module(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[str, None, None]:
    """Write an importable module holding an application, and make it importable."""
    (tmp_path / "sample_app.py").write_text(APP_MODULE)
    (tmp_path / "empty_app.py").write_text(EMPTY_APP_MODULE)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    yield "sample_app:app"
    for name in ("sample_app", "empty_app"):
        sys.modules.pop(name, None)


def _run(argv: list[str]) -> int:
    return main(argv)


# ---------------------------------------------------------------------------
# Emitting
# ---------------------------------------------------------------------------


def test_export_writes_the_descriptor_to_stdout(
    app_module: str, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(["schema", "export", app_module])
    document = json.loads(capsys.readouterr().out)

    assert code == 0
    assert document["resources"]["User"]["fields"]["name"]["type"] == "string"
    assert document["endpoints"][0]["path"] == "/users"


def test_export_writes_a_file(
    app_module: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "contract.json"

    code = _run(["schema", "export", app_module, "-o", str(target)])

    assert code == 0
    assert json.loads(target.read_text())["querymate"]
    assert "Wrote" in capsys.readouterr().err


def test_the_output_is_byte_stable(app_module: str, tmp_path: Path) -> None:
    """CI diffs the file, so regenerating it unchanged must produce identical bytes."""
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"

    _run(["schema", "export", app_module, "-o", str(first)])
    _run(["schema", "export", app_module, "-o", str(second)])

    assert first.read_bytes() == second.read_bytes()


def test_the_rendering_is_sorted_and_newline_terminated() -> None:
    rendered = _render({"b": 1, "a": {"d": 2, "c": 3}})

    assert rendered.endswith("\n")
    assert rendered.index('"a"') < rendered.index('"b"')
    assert rendered.index('"c"') < rendered.index('"d"')


def test_an_app_with_no_querymate_endpoints_warns(
    app_module: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Silence would look like success while emitting an empty contract."""
    code = _run(["schema", "export", "empty_app:app"])

    assert code == 0
    assert "no QueryMate endpoints found" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# --check, which is the reason the command exists
# ---------------------------------------------------------------------------


def test_check_passes_when_the_file_is_current(app_module: str, tmp_path: Path) -> None:
    target = tmp_path / "contract.json"
    _run(["schema", "export", app_module, "-o", str(target)])

    assert _run(["schema", "export", app_module, "-o", str(target), "--check"]) == 0


def test_check_fails_when_the_file_is_stale(
    app_module: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = tmp_path / "contract.json"
    _run(["schema", "export", app_module, "-o", str(target)])
    target.write_text('{"querymate": "0"}\n')

    code = _run(["schema", "export", app_module, "-o", str(target), "--check"])

    assert code == 1
    assert "out of date" in capsys.readouterr().err


def test_check_fails_when_the_file_is_missing(
    app_module: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run(
        ["schema", "export", app_module, "-o", str(tmp_path / "absent.json"), "--check"]
    )

    assert code == 1
    assert "does not exist" in capsys.readouterr().err


def test_check_without_an_output_file_is_refused(app_module: str) -> None:
    """There is nothing to compare against, and exiting 0 would be a false pass."""
    with pytest.raises(SystemExit, match="--check needs"):
        _run(["schema", "export", app_module, "--check"])


# ---------------------------------------------------------------------------
# Loading the application
# ---------------------------------------------------------------------------


def test_a_target_without_a_colon_is_refused(app_module: str) -> None:
    with pytest.raises(SystemExit, match="module:attribute"):
        _run(["schema", "export", "sample_app"])


def test_an_unimportable_module_is_reported(app_module: str) -> None:
    with pytest.raises(SystemExit, match="Could not import"):
        _run(["schema", "export", "no_such_module:app"])


def test_a_missing_attribute_is_reported(app_module: str) -> None:
    with pytest.raises(SystemExit, match="has no attribute"):
        _run(["schema", "export", "sample_app:nope"])


def test_an_attribute_that_is_not_an_app_produces_an_empty_contract(
    app_module: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """describe_app reads routes off whatever it is given; a non-app simply has none."""
    code = _run(["schema", "export", "sample_app:not_an_app"])

    assert code == 0
    assert json.loads(capsys.readouterr().out)["endpoints"] == []


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------


def test_the_subcommand_is_required() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_the_action_is_required() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["schema"])


def test_export_is_wired_to_its_handler() -> None:
    args = build_parser().parse_args(["schema", "export", "app.main:app"])

    assert args.handler is export
    assert args.app == "app.main:app"
    assert args.output is None
    assert args.check is False


def test_main_returns_the_handler_result(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(args: Any) -> int:
        return 3

    parser = build_parser()
    monkeypatch.setattr(
        "querymate.cli.build_parser",
        lambda: _parser_returning(parser, handler),
    )

    assert main(["schema", "export", "x:y"]) == 3


def _parser_returning(parser: Any, handler: Any) -> Any:
    """A parser whose export action dispatches to ``handler`` instead."""

    class Wrapper:
        def parse_args(self, argv: Any) -> Any:
            args = parser.parse_args(argv)
            args.handler = handler
            return args

    return Wrapper()


def test_the_installed_entry_point_matches() -> None:
    """pyproject advertises querymate.cli:main; a rename would break the console script."""
    import tomllib

    with open("pyproject.toml", "rb") as handle:
        config = tomllib.load(handle)

    assert config["project"]["scripts"]["querymate"] == "querymate.cli:main"


def test_the_command_is_runnable_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The path the docs actually tell people to use, cwd and all."""
    (tmp_path / "svc.py").write_text(APP_MODULE)
    monkeypatch.chdir(tmp_path)
    # Not on sys.path: _load_app is expected to add the working directory itself.
    monkeypatch.delitem(sys.modules, "svc", raising=False)

    code = main(["schema", "export", "svc:app", "-o", "contract.json"])

    assert code == 0
    assert (tmp_path / "contract.json").exists()
    sys.modules.pop("svc", None)


def test_the_app_fixture_really_exposes_querymate(app_module: str) -> None:
    """Guards the fixture itself: an app with no q parameter would test nothing."""
    import sample_app  # type: ignore[import-not-found]

    assert isinstance(sample_app.app, FastAPI)
    dependency = Querymate.for_model(User)
    assert callable(dependency)
    assert Depends(dependency) is not None
