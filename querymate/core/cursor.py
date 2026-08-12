"""Cursor (keyset) pagination: a page that stays correct while the data moves.

``offset`` asks the database to find and discard N rows before returning any, so page
1000 costs a thousand pages of work. Worse, it is defined against a snapshot that no
longer exists: insert a row while someone pages through, and every subsequent page
shifts by one - records get shown twice, or skipped entirely.

A cursor names the last row seen, in the query's own order, and the next page is
"everything strictly after that row". Nothing is counted, nothing is discarded, and an
insertion elsewhere in the table cannot shift the boundary.

Three things this requires, all of them enforced here rather than assumed:

* **A total order.** ``sort=["name"]`` is not one - two people named the same are in
  no defined order, so the boundary between pages is arbitrary. The primary key is
  appended as a tiebreaker to every cursor sort.
* **Explicit null placement.** Where nulls sort is dialect-defined; the comparison
  that finds "everything after" must agree with the ``ORDER BY`` that produced the
  cursor, so both are stated explicitly.
* **A cursor that matches its query.** Reusing a cursor against a different sort or
  filter would silently return a wrong page. Each cursor carries a fingerprint of the
  query that made it, and is refused otherwise.
"""

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_

from querymate.core.exceptions import QuerymateError


class InvalidCursorError(QuerymateError, ValueError):
    """A cursor that cannot be used for this query."""

    def __init__(self, detail: str, **context: Any) -> None:
        super().__init__(detail, **context)


@dataclass(frozen=True)
class SortKey:
    """One component of the total order a cursor is defined against."""

    field: str
    descending: bool = False


def fingerprint(model: str, keys: list[SortKey], filter: dict[str, Any] | None) -> str:
    """Identify the query a cursor belongs to.

    The order and the filter both decide what "the next row" means, so a cursor is
    only valid for the query that produced it. Comparing a short digest keeps the
    cursor small while still refusing a mismatch outright, which is better than
    silently returning a page from a different query.
    """
    material = json.dumps(
        {
            "model": model,
            "keys": [[key.field, key.descending] for key in keys],
            "filter": filter or {},
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def _encode_value(value: Any) -> Any:
    """Make one key value JSON-safe without losing what it is."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal | UUID):
        return str(value)
    return value


def _decode_value(value: Any, python_type: type | None) -> Any:
    """Restore a key value, using the column's type to read it back."""
    if value is None:
        return None
    try:
        if python_type is datetime:
            return datetime.fromisoformat(value)
        if python_type is date:
            return date.fromisoformat(value)
        if python_type is Decimal:
            return Decimal(value)
        if python_type is UUID:
            return UUID(value)
    except (TypeError, ValueError) as error:
        raise InvalidCursorError(f"Malformed cursor value: {value!r}") from error
    return value


def encode_cursor(values: list[Any], signature: str) -> str:
    """Encode the last row's key values into an opaque cursor.

    Opaque on purpose: the encoding is base64 rather than encryption, so it hides
    nothing, but making it unreadable at a glance keeps clients from constructing
    cursors by hand and depending on a layout that is free to change.
    """
    payload = json.dumps(
        {"k": signature, "v": [_encode_value(value) for value in values]},
        separators=(",", ":"),
    )
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


_MISMATCH = (
    "This cursor belongs to a different query. Start from the first page when the "
    "sort or the filter changes."
)


def decode_cursor(cursor: str, types: list[type | None], signature: str) -> list[Any]:
    """Decode a cursor into key values, or raise if it does not fit this query.

    Raises:
        InvalidCursorError: If the cursor is unreadable, or was made for a different
            sort or filter.
    """
    padding = "=" * (-len(cursor) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + padding))
    except (binascii.Error, UnicodeDecodeError, ValueError) as error:
        raise InvalidCursorError("The cursor is not readable.") from error

    if not isinstance(payload, dict) or not isinstance(payload.get("v"), list):
        raise InvalidCursorError("The cursor is not readable.")
    if payload.get("k") != signature or len(payload["v"]) != len(types):
        raise InvalidCursorError(_MISMATCH)

    return [
        _decode_value(value, type_)
        for value, type_ in zip(payload["v"], types, strict=True)
    ]


def order_by(column: Any, descending: bool) -> Any:
    """Order one key, stating where nulls go.

    Left to the dialect, nulls sort first in some databases and last in others. The
    keyset comparison has to agree with the ordering exactly or a page will be missed,
    so the placement is written down instead of inherited.
    """
    if descending:
        return column.desc().nullsfirst()
    return column.asc().nullslast()


def _strictly_after(column: Any, value: Any, descending: bool) -> Any:
    """The condition "this key is past the cursor's value", nulls included.

    Returns None when nothing can follow: ascending order puts nulls last, so a null
    key value has no successor of its own - only a later key can break the tie.
    """
    if descending:
        # Nulls first: everything not null comes after them.
        if value is None:
            return column.isnot(None)
        return column < value
    if value is None:
        return None
    # Nulls last: every null comes after any value.
    return or_(column > value, column.is_(None))


def _same(column: Any, value: Any) -> Any:
    """Tie on one key, treating two nulls as a tie."""
    if value is None:
        return column.is_(None)
    return column == value


def keyset_condition(columns: list[Any], keys: list[SortKey], values: list[Any]) -> Any:
    """Build "strictly after this row" for a multi-column order.

    The lexicographic expansion: the row is past the cursor if its first key is past,
    or the first key ties and the second is past, and so on. A row comparison
    (``(a, b) > (x, y)``) would say the same thing in one line but only where every
    key sorts the same way and no key is null, which is not the general case.
    """
    clauses: list[Any] = []
    for index, key in enumerate(keys):
        after = _strictly_after(columns[index], values[index], key.descending)
        if after is None:
            continue
        ties = [_same(columns[earlier], values[earlier]) for earlier in range(index)]
        clauses.append(and_(*ties, after) if ties else after)
    if not clauses:
        return None
    return or_(*clauses)
