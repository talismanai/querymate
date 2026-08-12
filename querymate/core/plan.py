"""The query plan: one canonical form everything else is derived from.

A query arrives as JSON, and the same query can arrive written several ways -
``["id", "name"]`` and ``["name", "id"]``, ``"+age"`` and ``"age"``, a filter's keys in
any order. That is fine for a parser and fatal for anything that has to *identify* a
query: a cache would store the same result under many keys, and two log lines for the
same work would not match.

The plan is that identity. It is derived from a validated :class:`~querymate.Querymate`
- never parsed from user input - and reduces it to a form where equivalent queries are
byte-identical:

* keys sorted at every level, unset blocks dropped
* selections sorted; ``and``/``or`` branches sorted, since their order cannot matter
* sort entries left in order, since theirs does, with ``+`` normalised away
* limit and offset spelled out rather than left implicit

The plan deliberately does not include *who* is asking. Authorization is resolved per
request and changes what the same query returns, so anything identity-sensitive - a
cache key above all - has to combine the plan with the principal's scope identity.
Keeping them separate is what makes forgetting the second half impossible to do
silently: :func:`querymate.core.cache.cache_key` requires it.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from querymate.core.config import settings


def _canonical(value: Any) -> Any:
    """Reduce a decoded JSON value to a form where equivalent values are identical."""
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, list):
        return [_canonical(item) for item in value]
    return value


def _sort_key(value: Any) -> str:
    """Order a list whose order carries no meaning, deterministically."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _canonical_selection(fields: Any) -> list[Any]:
    """Canonicalize a selection: sorted, since asking for two fields has no order."""
    if not isinstance(fields, list):
        return []
    canonical: list[Any] = []
    for field in fields:
        if isinstance(field, dict):
            canonical.append(
                {
                    name: (
                        _canonical_selection(value)
                        if isinstance(value, list)
                        else _canonical(value)
                    )
                    for name, value in sorted(field.items())
                }
            )
        else:
            canonical.append(field)
    return sorted(canonical, key=_sort_key)


def _canonical_filter(condition: Any) -> Any:
    """Canonicalize a filter, sorting the branches of ``and``/``or``.

    Their order cannot change the result, so two requests differing only in it are the
    same query and must reduce to the same bytes.
    """
    if not isinstance(condition, dict):
        return _canonical(condition)
    result: dict[str, Any] = {}
    for key in sorted(condition):
        value = condition[key]
        if key in ("and", "or") and isinstance(value, list):
            result[key] = sorted(
                (_canonical_filter(item) for item in value), key=_sort_key
            )
        else:
            result[key] = _canonical_filter(value)
    return result


@dataclass(frozen=True)
class QueryPlan:
    """A query reduced to its canonical form, with a digest identifying it.

    Attributes:
        model: Name of the model queried.
        body: The canonical query, as nested plain data.
    """

    model: str
    body: dict[str, Any]

    @property
    def canonical(self) -> str:
        """The plan as deterministic JSON. Equal queries produce equal strings."""
        return json.dumps(
            {"model": self.model, "query": self.body},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )

    @property
    def digest(self) -> str:
        """A short stable identifier for this query, independent of who asks."""
        return hashlib.sha256(self.canonical.encode()).hexdigest()[:32]


def build_plan(query: Any, model_name: str) -> QueryPlan:
    """Reduce a validated query to its plan.

    Args:
        query: A :class:`~querymate.Querymate`, already parsed and validated.
        model_name: The model it targets.
    """
    body: dict[str, Any] = {
        "select": _canonical_selection(query.select or []),
        "limit": (query.limit if query.limit is not None else settings.DEFAULT_LIMIT),
        "offset": (
            query.offset if query.offset is not None else settings.DEFAULT_OFFSET
        ),
    }
    if query.filter:
        body["filter"] = _canonical_filter(query.filter)
    if query.sort:
        # Order is meaningful here, so it is preserved; only the redundant '+' goes.
        body["sort"] = [
            entry[1:] if isinstance(entry, str) and entry.startswith("+") else entry
            for entry in query.sort
        ]
    if query.join_type:
        body["join_type"] = query.join_type
    if query.group_by is not None:
        body["group_by"] = _canonical(query.group_by)
    if query.aggregate:
        body["aggregate"] = _canonical(query.aggregate)
    if query.having:
        body["having"] = _canonical(query.having)
    if query.cursor:
        body["cursor"] = query.cursor
    if query.count:
        body["count"] = query.count
    return QueryPlan(model=model_name, body=body)
