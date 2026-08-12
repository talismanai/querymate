# type: ignore
"""Tests for grouped query functionality."""

from datetime import datetime

import pytest
from pydantic import ValidationError
from sqlmodel import Session

from querymate import Querymate
from querymate.core.grouping import (
    DateGranularity,
    GroupByConfig,
    GroupKeyExtractor,
)

from .helpers import capture_sql
from .models import Post, User

# -----------------------------------------------------------------------------
# GroupByConfig Tests
# -----------------------------------------------------------------------------


class TestGroupByConfig:
    """Tests for GroupByConfig parsing and validation."""

    def test_from_param_simple_string(self):
        """Test creating config from simple field name string."""
        config = GroupByConfig.from_param("status")
        assert config.field == "status"
        assert config.granularity is None
        assert config.tz_offset is None
        assert config.timezone is None
        assert not config.is_date_grouping

    def test_from_param_dict_with_granularity(self):
        """Test creating config with date granularity."""
        config = GroupByConfig.from_param(
            {"field": "created_at", "granularity": "month"}
        )
        assert config.field == "created_at"
        assert config.granularity == DateGranularity.MONTH
        assert config.is_date_grouping

    def test_from_param_dict_with_tz_offset(self):
        """Test creating config with timezone offset."""
        config = GroupByConfig.from_param(
            {"field": "created_at", "granularity": "day", "tz_offset": -3}
        )
        assert config.field == "created_at"
        assert config.granularity == DateGranularity.DAY
        assert config.tz_offset == -3
        assert config.get_tz_offset_hours() == -3

    def test_from_param_dict_with_timezone(self):
        """Test creating config with IANA timezone."""
        config = GroupByConfig.from_param(
            {
                "field": "created_at",
                "granularity": "hour",
                "timezone": "America/Sao_Paulo",
            }
        )
        assert config.field == "created_at"
        assert config.granularity == DateGranularity.HOUR
        assert config.timezone == "America/Sao_Paulo"
        assert config.get_tz_offset_hours() == -3

    def test_invalid_granularity(self):
        """Test that invalid granularity raises ValueError."""
        with pytest.raises(ValueError, match="Unsupported granularity"):
            GroupByConfig.from_param({"field": "created_at", "granularity": "invalid"})

    def test_both_tz_offset_and_timezone_raises(self):
        """Test that specifying both tz_offset and timezone raises error."""
        with pytest.raises(ValueError, match="Cannot specify both"):
            GroupByConfig.from_param(
                {
                    "field": "created_at",
                    "granularity": "day",
                    "tz_offset": -3,
                    "timezone": "America/Sao_Paulo",
                }
            )

    def test_unsupported_timezone(self):
        """Test that unsupported timezone raises error."""
        with pytest.raises(ValueError, match="Unsupported timezone"):
            GroupByConfig.from_param(
                {
                    "field": "created_at",
                    "granularity": "day",
                    "timezone": "Invalid/Timezone",
                }
            )

    def test_all_granularities(self):
        """Test all supported granularities."""
        for granularity in ["year", "month", "day", "hour", "minute"]:
            config = GroupByConfig.from_param(
                {"field": "created_at", "granularity": granularity}
            )
            assert config.granularity == DateGranularity(granularity)


class TestGroupKeyExtractor:
    """Tests for GroupKeyExtractor SQL expression generation."""

    def test_simple_field_expression(self):
        """Test that simple field returns column directly."""
        extractor = GroupKeyExtractor(dialect="sqlite")
        config = GroupByConfig(field="status")

        # For non-date grouping, should return the column itself
        column = User.status
        expr = extractor.get_group_key_expression(column, config)
        assert expr is column

    def test_date_grouping_sqlite(self):
        """Test SQLite date grouping expression generation."""
        extractor = GroupKeyExtractor(dialect="sqlite")
        config = GroupByConfig(field="created_at", granularity=DateGranularity.MONTH)

        column = User.created_at
        expr = extractor.get_group_key_expression(column, config)

        # Should return a strftime expression
        assert expr is not column


# -----------------------------------------------------------------------------
# Grouped Query Integration Tests
# -----------------------------------------------------------------------------


@pytest.fixture
def populated_db(db: Session):
    """Create test data with various statuses and dates."""
    # Create users with different statuses
    users = [
        User(
            id=1,
            name="Alice",
            email="alice@test.com",
            age=25,
            is_active=True,
            status="active",
            created_at=datetime(2024, 1, 15, 10, 30),
        ),
        User(
            id=2,
            name="Bob",
            email="bob@test.com",
            age=30,
            is_active=True,
            status="active",
            created_at=datetime(2024, 1, 20, 14, 45),
        ),
        User(
            id=3,
            name="Charlie",
            email="charlie@test.com",
            age=35,
            is_active=False,
            status="inactive",
            created_at=datetime(2024, 2, 10, 9, 0),
        ),
        User(
            id=4,
            name="Diana",
            email="diana@test.com",
            age=28,
            is_active=True,
            status="pending",
            created_at=datetime(2024, 2, 15, 11, 30),
        ),
        User(
            id=5,
            name="Eve",
            email="eve@test.com",
            age=32,
            is_active=False,
            status="inactive",
            created_at=datetime(2024, 3, 1, 8, 0),
        ),
    ]

    for user in users:
        db.add(user)

    # Create posts with different statuses
    posts = [
        Post(
            id=1,
            title="Post 1",
            content="Content 1",
            status="published",
            user_id=1,
            created_at=datetime(2024, 1, 15),
        ),
        Post(
            id=2,
            title="Post 2",
            content="Content 2",
            status="draft",
            user_id=1,
            created_at=datetime(2024, 1, 20),
        ),
        Post(
            id=3,
            title="Post 3",
            content="Content 3",
            status="published",
            user_id=2,
            created_at=datetime(2024, 2, 1),
        ),
        Post(
            id=4,
            title="Post 4",
            content="Content 4",
            status="draft",
            user_id=3,
            created_at=datetime(2024, 2, 15),
        ),
        Post(
            id=5,
            title="Post 5",
            content="Content 5",
            status="archived",
            user_id=4,
            created_at=datetime(2024, 3, 1),
        ),
    ]

    for post in posts:
        db.add(post)

    db.commit()
    return db


class TestGroupedQueries:
    """Integration tests for grouped query functionality."""

    def test_simple_grouping_by_status(self, populated_db: Session):
        """Test grouping users by status field."""
        querymate = Querymate(
            select=["id", "name", "status"],
            group_by="status",
            limit=10,
        )

        result = querymate.run_grouped(populated_db, User, dialect="sqlite")

        assert "groups" in result
        assert "truncated" in result
        assert result["truncated"] is False

        # Should have 3 groups: active, inactive, pending
        groups = result["groups"]
        assert len(groups) == 3

        # Groups should be ordered alphabetically
        group_keys = [g["key"] for g in groups]
        assert group_keys == ["active", "inactive", "pending"]

        # Check active group has 2 users
        active_group = next(g for g in groups if g["key"] == "active")
        assert len(active_group["items"]) == 2
        assert active_group["pagination"]["total"] == 2

    def test_grouping_with_filter(self, populated_db: Session):
        """Test grouping with filter applied."""
        querymate = Querymate(
            select=["id", "name", "status"],
            filter={"is_active": True},
            group_by="status",
            limit=10,
        )

        result = querymate.run_grouped(populated_db, User, dialect="sqlite")

        groups = result["groups"]
        # Should only have active and pending (where is_active=True)
        group_keys = [g["key"] for g in groups]
        assert "inactive" not in group_keys

    def test_grouping_with_sorting(self, populated_db: Session):
        """Test that sorting is applied within each group."""
        querymate = Querymate(
            select=["id", "name", "status", "age"],
            group_by="status",
            sort=["-age"],  # Sort by age descending
            limit=10,
        )

        result = querymate.run_grouped(populated_db, User, dialect="sqlite")

        # Check that items within each group are sorted by age descending
        for group in result["groups"]:
            items = group["items"]
            if len(items) > 1:
                ages = [item["age"] for item in items]
                assert ages == sorted(ages, reverse=True)

    def test_per_group_pagination(self, populated_db: Session):
        """Test that limit applies per group."""
        querymate = Querymate(
            select=["id", "name", "status"],
            group_by="status",
            limit=1,  # Only 1 item per group
        )

        result = querymate.run_grouped(populated_db, User, dialect="sqlite")

        # Each group should have at most 1 item
        for group in result["groups"]:
            assert len(group["items"]) <= 1
            # But pagination should show the real total
            if group["key"] == "active":
                assert group["pagination"]["total"] == 2
            elif group["key"] == "inactive":
                assert group["pagination"]["total"] == 2

    def test_max_limit_truncation(self, populated_db: Session):
        """Test that MAX_LIMIT truncates total results."""
        # Add more users to exceed max limit
        for i in range(10, 250):
            populated_db.add(
                User(
                    id=i,
                    name=f"User{i}",
                    email=f"user{i}@test.com",
                    age=20 + (i % 50),
                    is_active=True,
                    status=f"status_{i % 5}",
                    created_at=datetime.now(),
                )
            )
        populated_db.commit()

        querymate = Querymate(
            select=["id", "name", "status"],
            group_by="status",
            limit=100,  # High per-group limit
        )

        result = querymate.run_grouped(populated_db, User, dialect="sqlite")

        # Total items should not exceed MAX_LIMIT (200)
        total_items = sum(len(g["items"]) for g in result["groups"])
        assert total_items <= 200

    def test_date_grouping_by_month(self, populated_db: Session):
        """Test grouping by date with month granularity."""
        querymate = Querymate(
            select=["id", "name", "created_at"],
            group_by={"field": "created_at", "granularity": "month"},
            limit=10,
        )

        result = querymate.run_grouped(populated_db, User, dialect="sqlite")

        groups = result["groups"]
        # Should have groups for 2024-01, 2024-02, 2024-03
        group_keys = [g["key"] for g in groups]
        assert "2024-01" in group_keys
        assert "2024-02" in group_keys
        assert "2024-03" in group_keys

    def test_date_grouping_by_year(self, populated_db: Session):
        """Test grouping by date with year granularity."""
        querymate = Querymate(
            select=["id", "name", "created_at"],
            group_by={"field": "created_at", "granularity": "year"},
            limit=10,
        )

        result = querymate.run_grouped(populated_db, User, dialect="sqlite")

        groups = result["groups"]
        # All users are in 2024
        assert len(groups) == 1
        assert groups[0]["key"] == "2024"
        assert len(groups[0]["items"]) == 5

    def test_date_grouping_by_day(self, populated_db: Session):
        """Test grouping by date with day granularity."""
        querymate = Querymate(
            select=["id", "name", "created_at"],
            group_by={"field": "created_at", "granularity": "day"},
            limit=10,
        )

        result = querymate.run_grouped(populated_db, User, dialect="sqlite")

        groups = result["groups"]
        # Each user has a unique day
        assert len(groups) == 5

    def test_date_grouping_with_timezone_offset(self, populated_db: Session):
        """Test date grouping with timezone offset."""
        querymate = Querymate(
            select=["id", "name", "created_at"],
            group_by={
                "field": "created_at",
                "granularity": "day",
                "tz_offset": -3,  # UTC-3
            },
            limit=10,
        )

        result = querymate.run_grouped(populated_db, User, dialect="sqlite")

        # Should complete without error
        assert "groups" in result
        assert result["truncated"] is False

    def test_group_by_not_set_raises(self, populated_db: Session):
        """Test that run_grouped raises if group_by is not set."""
        querymate = Querymate(
            select=["id", "name"],
            limit=10,
        )

        with pytest.raises(ValueError, match="group_by parameter is required"):
            querymate.run_grouped(populated_db, User, dialect="sqlite")

    def test_post_grouping_by_status(self, populated_db: Session):
        """Test grouping posts by status."""
        querymate = Querymate(
            select=["id", "title", "status"],
            group_by="status",
            limit=10,
        )

        result = querymate.run_grouped(populated_db, Post, dialect="sqlite")

        groups = result["groups"]
        group_keys = [g["key"] for g in groups]

        # Should have archived, draft, published
        assert "archived" in group_keys
        assert "draft" in group_keys
        assert "published" in group_keys

    def test_empty_result_grouping(self, populated_db: Session):
        """Test grouping with filter that matches no records."""
        querymate = Querymate(
            select=["id", "name", "status"],
            filter={"age": {"gt": 1000}},  # No users this old
            group_by="status",
            limit=10,
        )

        result = querymate.run_grouped(populated_db, User, dialect="sqlite")

        assert result["groups"] == []
        assert result["truncated"] is False

    def test_pagination_metadata_per_group(self, populated_db: Session):
        """Test that each group has correct pagination metadata."""
        querymate = Querymate(
            select=["id", "name", "status"],
            group_by="status",
            limit=1,
            offset=0,
        )

        result = querymate.run_grouped(populated_db, User, dialect="sqlite")

        for group in result["groups"]:
            pagination = group["pagination"]
            assert "total" in pagination
            assert "page" in pagination
            assert "size" in pagination
            assert "pages" in pagination
            assert pagination["page"] == 1
            assert pagination["size"] == 1


class TestGroupingQueryCount:
    """Grouping used to issue one query per distinct group key.

    A grouped request therefore cost time proportional to how many distinct values
    the data happened to contain - a property of the data, not of the request. A
    window function pages every group in one pass instead.
    """

    def _seed(self, db: Session, groups: int) -> None:
        db.add(User(id=1, name="A", email="a@x.com", age=30, is_active=True))
        for idx in range(1, groups * 3 + 1):
            db.add(
                Post(
                    id=idx,
                    title=f"Post {idx}",
                    content="c",
                    user_id=1,
                    status=f"status-{idx % groups}",
                )
            )
        db.commit()

    def test_query_count_does_not_grow_with_group_count(self, db: Session) -> None:
        self._seed(db, groups=25)

        querymate = Querymate(
            select=["id", "title", "status"], group_by="status", limit=5
        )
        with capture_sql(db) as statements:
            result = querymate.run_grouped(db, Post, dialect="sqlite")

        assert len(result["groups"]) == 25
        assert len(statements) <= 3, f"expected a constant count, got {statements}"

    def test_every_group_is_paged_to_the_limit(self, db: Session) -> None:
        self._seed(db, groups=4)

        querymate = Querymate(
            select=["id", "title", "status"], group_by="status", limit=2
        )
        result = querymate.run_grouped(db, Post, dialect="sqlite")

        assert len(result["groups"]) == 4
        for group in result["groups"]:
            assert len(group["items"]) == 2
            assert group["pagination"]["total"] == 3

    def test_offset_applies_within_each_group(self, db: Session) -> None:
        self._seed(db, groups=2)

        first = Querymate(select=["id"], group_by="status", limit=1).run_grouped(
            db, Post, dialect="sqlite"
        )
        second = Querymate(
            select=["id"], group_by="status", limit=1, offset=1
        ).run_grouped(db, Post, dialect="sqlite")

        for group_a, group_b in zip(first["groups"], second["groups"], strict=True):
            assert group_a["key"] == group_b["key"]
            assert group_a["items"] != group_b["items"]


class TestGroupKeyExtractorInternals:
    """The parts of key extraction the end-to-end grouped tests do not reach.

    PostgreSQL is one of them: the SQL it emits differs from SQLite's entirely, and
    the suite runs on SQLite. Compiling the expression against the PostgreSQL dialect
    checks what would actually be sent.
    """

    def _postgres_sql(self, config: GroupByConfig) -> str:
        from sqlalchemy.dialects import postgresql

        expression = GroupKeyExtractor(dialect="postgresql").get_group_key_expression(
            User.created_at, config
        )
        return str(
            expression.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )

    def test_a_field_with_no_granularity_groups_on_the_column(self):
        extractor = GroupKeyExtractor(dialect="postgresql")

        expression = extractor.get_group_key_expression(
            User.status, GroupByConfig(field="status")
        )

        assert expression is User.status

    @pytest.mark.parametrize(
        ("granularity", "format_string"),
        [
            ("year", "YYYY"),
            ("month", "YYYY-MM"),
            ("day", "YYYY-MM-DD"),
            ("hour", 'YYYY-MM-DD"T"HH24'),
            ("minute", 'YYYY-MM-DD"T"HH24:MI'),
        ],
    )
    def test_postgres_truncates_and_formats_per_granularity(
        self, granularity, format_string
    ):
        sql = self._postgres_sql(
            GroupByConfig(field="created_at", granularity=granularity)
        )

        assert "date_trunc" in sql
        assert format_string in sql

    def test_postgres_applies_a_timezone_offset_as_an_interval(self):
        sql = self._postgres_sql(
            GroupByConfig(field="created_at", granularity="day", tz_offset=-3)
        )

        assert "make_interval" in sql
        assert "-3" in sql

    def test_postgres_without_an_offset_does_not_shift_the_column(self):
        sql = self._postgres_sql(
            GroupByConfig(field="created_at", granularity="day", tz_offset=0)
        )

        assert "make_interval" not in sql

    def test_sqlite_applies_a_timezone_offset_as_a_modifier(self):
        expression = GroupKeyExtractor(dialect="sqlite").get_group_key_expression(
            User.created_at,
            GroupByConfig(field="created_at", granularity="day", tz_offset=-3),
        )
        sql = str(expression.compile(compile_kwargs={"literal_binds": True}))

        assert "-3 hours" in sql


class TestGranularityValidation:
    """The validator accepts three kinds of input and rejects the rest."""

    def test_an_enum_member_passes_through(self):
        config = GroupByConfig(field="created_at", granularity=DateGranularity.MONTH)

        assert config.granularity is DateGranularity.MONTH

    def test_a_string_is_normalised_case_insensitively(self):
        config = GroupByConfig(field="created_at", granularity="MONTH")

        assert config.granularity is DateGranularity.MONTH

    def test_none_stays_none(self):
        assert GroupByConfig(field="created_at", granularity=None).granularity is None

    def test_a_value_of_the_wrong_type_is_refused(self):
        with pytest.raises(ValidationError, match="Invalid granularity type"):
            GroupByConfig(field="created_at", granularity=7)
