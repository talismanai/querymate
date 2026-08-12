"""The query plan: one canonical form everything else is derived from.

A query arrives as JSON, and the same query can arrive written several ways -
``["id", "name"]`` and ``["name", "id"]``, ``"+age"`` and ``"age"``, a filter's keys in
any order. That is fine for a parser and fatal for anything that has to *identify* a
query: a cache would store the same result under many keys, a budget could be evaded
by reordering, and two log lines for the same work would not match.

The plan is that identity. It is derived from a validated :class:`~querymate.Querymate`
- never parsed from user input - and reduces it to a form where equivalent queries are
byte-identical:

* keys sorted at every level, unset blocks dropped
* selections sorted; ``and``/``or`` branches sorted, since their order cannot matter
* sort entries left in order, since theirs does, with ``+`` normalised away
* limit and offset spelled out rather than left implicit

From that one form come two things that must not disagree: the cache key
(:mod:`querymate.core.cache`) and the cost estimate below.

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
from querymate.core.exceptions import QuerymateError

# Roughly what each part of a query costs the database, in arbitrary units. These are
# an ordering, not a time estimate: the point is that a query asking for five levels of
# relationships scores far above one asking for a page of columns, so a ceiling can be
# set without predicting milliseconds.
COST_BASE = 1
# Each expanded relationship is one more round trip, and one nested deeper multiplies
# the rows that trip returns.
COST_RELATIONSHIP = 10
# A relationship filter is a correlated EXISTS - cheap next to a join, not free.
COST_RELATIONSHIP_FILTER = 5
# Sorting by a related field is a correlated aggregate evaluated per candidate row.
COST_RELATIONSHIP_SORT = 20
# A computed field is a correlated subquery per row.
COST_COMPUTED = 5
COST_AGGREGATE = 2
COST_GROUP_BY = 5
# Counting the whole set is a second full scan of the filtered rows.
COST_TOTAL = 10
# Page size, charged per ten rows so a default page barely registers.
COST_PER_ROWS = 10


class BudgetExceededError(QuerymateError):
    """A query whose estimated cost is above what this caller may spend.

    A 400 rather than a 429: nothing is being rate-limited, and waiting will not help.
    The query as written is too expensive, and the client has to ask for less.
    """

    def __init__(self, cost: int, budget: int) -> None:
        super().__init__(
            f"This query's estimated cost is {cost}, above the limit of {budget}. "
            "Ask for fewer relationships, a smaller page, or split it up.",
            cost=cost,
            budget=budget,
        )


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
    """A query reduced to its canonical form, with a digest and a cost.

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

    def cost(self) -> int:
        """Estimate what this query will cost, in the units documented above.

        An ordering rather than a prediction: it exists so a ceiling can distinguish
        "a page of columns" from "five levels of relationships sorted by a related
        field", which is the distinction a budget needs to make.
        """
        total = COST_BASE
        relationships, computed = _selection_cost(self.body.get("select") or [], 1)
        total += relationships + computed

        for key in self.body.get("filter") or {}:
            if "." in key:
                total += COST_RELATIONSHIP_FILTER
        for entry in self.body.get("sort") or []:
            if isinstance(entry, str) and "." in entry:
                total += COST_RELATIONSHIP_SORT

        total += COST_AGGREGATE * len(self.body.get("aggregate") or {})
        if self.body.get("group_by") is not None:
            total += COST_GROUP_BY
        if self.body.get("with_total"):
            total += COST_TOTAL

        limit = self.body.get("limit") or 0
        total += int(limit) // COST_PER_ROWS
        return total

    def check_budget(self, budget: int | None) -> None:
        """Refuse the query if it costs more than ``budget`` allows.

        Raises:
            BudgetExceededError: If the estimate is above the budget.
        """
        if not budget:
            return
        cost = self.cost()
        if cost > budget:
            raise BudgetExceededError(cost, budget)


def _selection_cost(fields: Any, depth: int) -> tuple[int, int]:
    """Cost of a selection tree: relationships weighted by depth, plus computed fields.

    A relationship two levels down costs more than one at the root because the rows it
    returns multiply with everything above it.
    """
    relationships = 0
    computed = 0
    for field in fields or []:
        if isinstance(field, dict):
            for _, value in field.items():
                relationships += COST_RELATIONSHIP * depth
                nested = value if isinstance(value, list) else value.get("select")
                deeper_relationships, deeper_computed = _selection_cost(
                    nested, depth + 1
                )
                relationships += deeper_relationships
                computed += deeper_computed
        elif isinstance(field, str) and field.endswith("_count"):
            # Cheap to check by name and only ever an overestimate: a stored column
            # called `login_count` is charged for a subquery it does not run.
            computed += COST_COMPUTED
    return relationships, computed


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
    if query.with_total:
        body["with_total"] = True
    return QueryPlan(model=model_name, body=body)
