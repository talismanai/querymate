"""
QueryMate - A Python library for building and executing database queries.
"""

__version__ = "0.5.0"  # Update this with your actual version

from .core.config import QueryMateSettings as QueryMateSettings
from .core.config import settings as settings
from .core.filter import ContainsPredicate as ContainsPredicate
from .core.filter import EndsWithPredicate as EndsWithPredicate
from .core.filter import EqualPredicate as EqualPredicate
from .core.filter import FilterBuilder as FilterBuilder
from .core.filter import (
    GreaterThanOrEqualPredicate as GreaterThanOrEqualPredicate,
)
from .core.filter import GreaterThanPredicate as GreaterThanPredicate
from .core.filter import InPredicate as InPredicate
from .core.filter import IsNotNullPredicate as IsNotNullPredicate
from .core.filter import IsNullPredicate as IsNullPredicate
from .core.filter import LessThanOrEqualPredicate as LessThanOrEqualPredicate
from .core.filter import LessThanPredicate as LessThanPredicate
from .core.filter import NotEqualPredicate as NotEqualPredicate
from .core.filter import NotInPredicate as NotInPredicate
from .core.filter import Predicate as Predicate
from .core.filter import StartsWithPredicate as StartsWithPredicate
from .core.query_builder import QueryBuilder as QueryBuilder
from .core.querymate import Querymate as Querymate

# Type aliases for better IDE support
QueryMateType: type[Querymate] = Querymate
QueryBuilderType: type[QueryBuilder] = QueryBuilder
FilterBuilderType: type[FilterBuilder] = FilterBuilder
