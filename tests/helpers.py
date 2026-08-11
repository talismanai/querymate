"""Shared test helpers."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import event
from sqlmodel import Session


@contextmanager
def capture_sql(session: Session) -> Generator[list[str], None, None]:
    """Collect every SQL statement executed while the block runs.

    Asserting a constant statement count regardless of data volume is the only
    reliable way to catch an N+1; counting returned rows cannot see one.
    """
    statements: list[str] = []
    engine = session.get_bind()

    def before(
        conn: Any,
        cursor: Any,
        statement: str,
        params: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", before)
