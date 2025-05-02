"""
QueryMate - A Python library for building and executing database queries.
"""

__version__ = "0.5.1"  # Update this with your actual version

from .core.config import QueryMateSettings as QueryMateSettings
from .core.config import settings as settings
from .core.filter import BlankPredicate as BlankPredicate
from .core.filter import ContainsPredicate as ContainsPredicate
from .core.filter import DoesNotMatchAllPredicate as DoesNotMatchAllPredicate
from .core.filter import DoesNotMatchAnyPredicate as DoesNotMatchAnyPredicate
from .core.filter import DoesNotMatchPredicate as DoesNotMatchPredicate
from .core.filter import EndAllPredicate as EndAllPredicate
from .core.filter import EndAnyPredicate as EndAnyPredicate
from .core.filter import EndPredicate as EndPredicate
from .core.filter import EndsWithPredicate as EndsWithPredicate
from .core.filter import EqualPredicate as EqualPredicate
from .core.filter import FalsePredicate as FalsePredicate
from .core.filter import FilterBuilder as FilterBuilder
from .core.filter import (
    GreaterThanOrEqualPredicate as GreaterThanOrEqualPredicate,
)
from .core.filter import GreaterThanPredicate as GreaterThanPredicate
from .core.filter import GtAllPredicate as GtAllPredicate
from .core.filter import GtAnyPredicate as GtAnyPredicate
from .core.filter import GteqAllPredicate as GteqAllPredicate
from .core.filter import GteqAnyPredicate as GteqAnyPredicate
from .core.filter import IContAllPredicate as IContAllPredicate
from .core.filter import IContAnyPredicate as IContAnyPredicate
from .core.filter import IContPredicate as IContPredicate
from .core.filter import InPredicate as InPredicate
from .core.filter import IsNotNullPredicate as IsNotNullPredicate
from .core.filter import IsNullPredicate as IsNullPredicate
from .core.filter import LessThanOrEqualPredicate as LessThanOrEqualPredicate
from .core.filter import LessThanPredicate as LessThanPredicate
from .core.filter import LtAllPredicate as LtAllPredicate
from .core.filter import LtAnyPredicate as LtAnyPredicate
from .core.filter import LteqAllPredicate as LteqAllPredicate
from .core.filter import LteqAnyPredicate as LteqAnyPredicate
from .core.filter import MatchesAllPredicate as MatchesAllPredicate
from .core.filter import MatchesAnyPredicate as MatchesAnyPredicate
from .core.filter import MatchesPredicate as MatchesPredicate
from .core.filter import NotEndAllPredicate as NotEndAllPredicate
from .core.filter import NotEndAnyPredicate as NotEndAnyPredicate
from .core.filter import NotEndPredicate as NotEndPredicate
from .core.filter import NotEqAllPredicate as NotEqAllPredicate
from .core.filter import NotEqualPredicate as NotEqualPredicate
from .core.filter import NotIContAllPredicate as NotIContAllPredicate
from .core.filter import NotIContAnyPredicate as NotIContAnyPredicate
from .core.filter import NotIContPredicate as NotIContPredicate
from .core.filter import NotInPredicate as NotInPredicate
from .core.filter import NotStartAllPredicate as NotStartAllPredicate
from .core.filter import NotStartAnyPredicate as NotStartAnyPredicate
from .core.filter import NotStartPredicate as NotStartPredicate
from .core.filter import Predicate as Predicate
from .core.filter import PresentPredicate as PresentPredicate
from .core.filter import StartAllPredicate as StartAllPredicate
from .core.filter import StartAnyPredicate as StartAnyPredicate
from .core.filter import StartPredicate as StartPredicate
from .core.filter import StartsWithPredicate as StartsWithPredicate
from .core.filter import TruePredicate as TruePredicate
from .core.query_builder import QueryBuilder as QueryBuilder
from .core.querymate import Querymate as Querymate

# Type aliases for better IDE support
QueryMateType: type[Querymate] = Querymate
QueryBuilderType: type[QueryBuilder] = QueryBuilder
FilterBuilderType: type[FilterBuilder] = FilterBuilder
