"""Exceptions raised when a query cannot be honoured.

A query is built from untrusted input, so most failures are the caller's fault, not
the server's. Previously they surfaced either as a log warning that silently changed
the response or as a bare ``AttributeError``/``ValueError`` that reached the client as
a 500. Both are wrong: the first hides a mistake, the second blames the server for it.

Everything here carries an HTTP status and a structured payload naming the offending
part of the query, so an API can answer with a 4xx a client can act on. Use
:func:`querymate.core.exceptions.install_exception_handler` to wire that up, or catch
:class:`QuerymateError` yourself.
"""

from typing import Any


class QuerymateError(Exception):
    """Base class for every error QueryMate raises about a query.

    Attributes:
        status_code (int): The HTTP status this error should map to.
        detail (str): Human-readable explanation.
        context (dict[str, Any]): Structured details - the field, relationship,
            operator, or limit involved.
    """

    status_code: int = 400

    def __init__(self, detail: str, **context: Any) -> None:
        self.detail = detail
        self.context = context
        super().__init__(detail)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable body for an error response."""
        return {
            "error": type(self).__name__,
            "detail": self.detail,
            **self.context,
        }


class InvalidQueryError(QuerymateError, ValueError):
    """The ``q`` parameter is not valid JSON, or is not shaped like a query.

    Also a ``ValueError``, which is what parsing ``q`` used to raise.
    """


class InvalidSortError(QuerymateError, ValueError):
    """A sort entry is malformed and cannot be applied faithfully."""

    def __init__(self, sort: Any, detail: str) -> None:
        super().__init__(detail, sort=sort)


class EntityNotPermittedError(QuerymateError, PermissionError):
    """A query attempts to access an entity forbidden by application policy."""

    status_code = 403

    def __init__(self, entity: str, path: str, operation: str) -> None:
        super().__init__(
            f"Entity '{entity}' is not permitted for this query.",
            entity=entity,
            path=path,
            operation=operation,
        )


class UnknownFieldError(QuerymateError, AttributeError):
    """A requested field does not exist on the model.

    Also an ``AttributeError`` so that existing callers catching that keep working -
    resolving a field really is an attribute lookup, and the two readings agree.
    """

    def __init__(
        self, field: str, model: str, valid_fields: list[str] | None = None
    ) -> None:
        super().__init__(
            f"Field '{field}' not found in {model}.",
            field=field,
            model=model,
            **({"valid_fields": sorted(valid_fields)} if valid_fields else {}),
        )


class UnknownRelationshipError(QuerymateError, AttributeError):
    """A requested relationship does not exist on the model."""

    def __init__(
        self, relationship: str, model: str, valid_relationships: Any = None
    ) -> None:
        super().__init__(
            f"Relationship '{relationship}' not found in {model}.",
            relationship=relationship,
            model=model,
            **(
                {"valid_relationships": sorted(valid_relationships)}
                if valid_relationships
                else {}
            ),
        )


class UnsupportedOperatorError(QuerymateError, ValueError):
    """A filter used an operator QueryMate does not implement.

    Also a ``ValueError``, which is what this used to raise.
    """

    def __init__(self, operator: str, valid_operators: list[str] | None = None) -> None:
        super().__init__(
            f"Unsupported operator: '{operator}'.",
            operator=operator,
            **({"valid_operators": sorted(valid_operators)} if valid_operators else {}),
        )


class DepthExceededError(QuerymateError):
    """The selection nests relationships more deeply than allowed.

    Depth is bounded because each level costs a query and can widen the result set;
    without a ceiling a single request can be made arbitrarily expensive.
    """

    def __init__(self, depth: int, max_depth: int) -> None:
        super().__init__(
            f"Selection nests {depth} levels deep, exceeding the maximum of "
            f"{max_depth}.",
            depth=depth,
            max_depth=max_depth,
        )


class SelectionTooLargeError(QuerymateError):
    """The selection asks for more nodes than allowed.

    Bounds the breadth of a request the way ``DepthExceededError`` bounds its depth.
    """

    def __init__(self, nodes: int, max_nodes: int) -> None:
        super().__init__(
            f"Selection contains {nodes} nodes, exceeding the maximum of {max_nodes}.",
            nodes=nodes,
            max_nodes=max_nodes,
        )


def install_exception_handler(app: Any) -> None:
    """Register a FastAPI handler turning QueryMate errors into 4xx responses.

    Without it these propagate as unhandled exceptions and FastAPI answers 500, which
    misreports a malformed query as a server fault.

    Args:
        app: The FastAPI application.

    Example:
        ```python
        from querymate import install_exception_handler

        app = FastAPI()
        install_exception_handler(app)
        ```
    """
    from fastapi import Request
    from fastapi.responses import JSONResponse

    async def handler(_: "Request", exc: Exception) -> "JSONResponse":
        assert isinstance(exc, QuerymateError)
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict())

    app.add_exception_handler(QuerymateError, handler)
