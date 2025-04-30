"""
Core functionality for QueryMate.
"""

from querymate.core.config import QueryMateSettings as QueryMateSettings
from querymate.core.config import settings as settings
from querymate.core.filter import ContainsPredicate as ContainsPredicate
from querymate.core.filter import EndsWithPredicate as EndsWithPredicate
from querymate.core.filter import EqualPredicate as EqualPredicate
from querymate.core.filter import FilterBuilder as FilterBuilder
from querymate.core.filter import (
    GreaterThanOrEqualPredicate as GreaterThanOrEqualPredicate,
)
from querymate.core.filter import GreaterThanPredicate as GreaterThanPredicate
from querymate.core.filter import InPredicate as InPredicate
from querymate.core.filter import IsNotNullPredicate as IsNotNullPredicate
from querymate.core.filter import IsNullPredicate as IsNullPredicate
from querymate.core.filter import (
    LessThanOrEqualPredicate as LessThanOrEqualPredicate,
)
from querymate.core.filter import LessThanPredicate as LessThanPredicate
from querymate.core.filter import NotEqualPredicate as NotEqualPredicate
from querymate.core.filter import NotInPredicate as NotInPredicate
from querymate.core.filter import Predicate as Predicate
from querymate.core.filter import StartsWithPredicate as StartsWithPredicate
from querymate.core.query_builder import QueryBuilder as QueryBuilder
from querymate.core.querymate import Querymate as Querymate
