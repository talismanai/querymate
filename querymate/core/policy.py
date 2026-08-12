"""Application-wide permission to query or traverse mapped entities."""

from collections.abc import Collection
from dataclasses import dataclass

from querymate.core.compat import ModelClass
from querymate.core.exceptions import EntityNotPermittedError


@dataclass(frozen=True)
class EntityPolicy:
    """An immutable allow/block policy shared by every configured query."""

    allowed: frozenset[ModelClass] | None
    blocked: frozenset[ModelClass]

    @classmethod
    def create(
        cls,
        allowed: Collection[ModelClass] | None = None,
        blocked: Collection[ModelClass] | None = None,
    ) -> "EntityPolicy":
        """Validate and freeze setup declarations."""
        allowed_set = frozenset(allowed) if allowed is not None else None
        blocked_set = frozenset(blocked or ())
        overlap = (allowed_set or frozenset()) & blocked_set
        if overlap:
            names = ", ".join(sorted(model.__name__ for model in overlap))
            raise ValueError(
                f"Entities cannot be both allowed and blocked: {names}. "
                "Remove them from the allow-list; blocked entities always win."
            )
        return cls(allowed=allowed_set, blocked=blocked_set)

    @staticmethod
    def _matches(model: ModelClass, declarations: frozenset[ModelClass]) -> bool:
        return any(issubclass(model, declared) for declared in declarations)

    def permits(self, model: ModelClass) -> bool:
        """Return whether ``model`` is globally queryable."""
        if self._matches(model, self.blocked):
            return False
        return self.allowed is None or self._matches(model, self.allowed)

    def check(self, model: ModelClass, *, path: str, operation: str) -> None:
        """Fail before SQL when a query reaches a forbidden model."""
        if not self.permits(model):
            raise EntityNotPermittedError(model.__name__, path, operation)
