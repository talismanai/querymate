from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import Engine, case
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, SQLModel, create_engine, desc, select
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.pool import StaticPool

from querymate.core.query_builder import QueryBuilder
from tests.models import Post, User


@pytest.fixture
def app() -> FastAPI:
    app = FastAPI()
    return app


@pytest.fixture
def engine() -> Engine:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def db(engine: Engine) -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session


@pytest.fixture
async def async_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def async_db(async_engine: Any) -> AsyncGenerator[AsyncSession, None]:
    async_session = sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:  # type: ignore
        yield session


# ================================
# Test cases for select
# ================================
def test_select() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    expected_query = select(User.id, User.name, Post.id, Post.title).join(Post)
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_select_with_duplicated_fields() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", "name", {"posts": ["id", "title", "id"]}])
    expected_query = select(User.id, User.name, Post.id, Post.title).join(Post)
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_select_with_asterisk() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["*", {"posts": ["*"]}])

    # Get all field names from the models dynamically
    user_fields = set(User.model_fields.keys())
    post_fields = set(Post.model_fields.keys())

    # Check that both queries have the same compiled structure
    actual_sql = str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    )

    # Verify that the query includes all expected fields
    for field in user_fields:
        assert (
            f'"user".{field}' in actual_sql
            or f'"user".{field}' in actual_sql.replace('"', "")
        ), f"Missing User field: {field}"
    for field in post_fields:
        # Handle aliased fields (when field names conflict)
        assert f"post.{field}" in actual_sql or f"{field}" in actual_sql, (
            f"Missing Post field: {field}"
        )

    # Verify JOIN clause is present
    assert "JOIN post ON" in actual_sql


def test_select_with_asterisk_and_duplicated_fields() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["*", "id", "name", {"posts": ["id", "*", "title"]}])

    # Get all field names from the models dynamically
    user_fields = set(User.model_fields.keys())
    post_fields = set(Post.model_fields.keys())

    # Check that the query includes all expected fields
    actual_sql = str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    )

    # Verify that the query includes all expected fields
    for field in user_fields:
        assert (
            f'"user".{field}' in actual_sql
            or f'"user".{field}' in actual_sql.replace('"', "")
        ), f"Missing User field: {field}"
    for field in post_fields:
        # Handle aliased fields (when field names conflict)
        assert f"post.{field}" in actual_sql or f"{field}" in actual_sql, (
            f"Missing Post field: {field}"
        )

    # Verify JOIN clause is present
    assert "JOIN post ON" in actual_sql


# ================================
# Test cases for filter
# ================================
def test_filter() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    query_builder.apply_filter({"age": {"gt": 25}})
    expected_query = (
        select(User.id, User.name, Post.id, Post.title).where(User.age > 25).join(Post)
    )
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_filter_with_nested_fields() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    query_builder.apply_filter({"posts.title": {"cont": "Python"}})
    expected_query = (
        select(User.id, User.name, Post.id, Post.title)
        .where(Post.title.contains("Python"))  # type: ignore
        .join(Post)
    )
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_filter_combines_ne_and_gt() -> None:
    """QueryBuilder supports combining NE with other operators on root fields."""
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name"]).apply_filter(
        {"age": {"gt": 20}, "name": {"ne": "John"}}
    )
    expected_query = select(User.id, User.name).where(
        User.age > 20, User.name != "John"
    )
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_filter_combines_ne_with_relationship_filter() -> None:
    """Combine NE on root field with a relationship filter."""
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}]).apply_filter(
        {"posts.title": {"cont": "Post"}, "name": {"ne": "John"}}
    )
    expected_query = (
        select(User.id, User.name, Post.id, Post.title)
        .where(Post.title.contains("Post"), User.name != "John")  # type: ignore
        .join(Post)
    )
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_filter_with_or_same_property() -> None:
    """Support OR conditions on the same property (e.g., status=1 or status=2)."""
    builder = QueryBuilder(User)
    builder.apply_select(["id", "name"]).apply_filter(
        {"or": [{"age": {"eq": 25}}, {"age": {"eq": 30}}]}
    )
    compiled = str(builder.query.compile(compile_kwargs={"literal_binds": True}))
    assert '"user".age = 25' in compiled
    assert '"user".age = 30' in compiled
    assert " OR " in compiled


def test_filter_with_and_or_multiple_properties() -> None:
    """Support mixing AND/OR across multiple properties."""
    builder = QueryBuilder(User)
    builder.apply_select(["id", "name"]).apply_filter(
        {
            "and": [
                {"or": [{"age": {"gt": 18}}, {"age": {"eq": 18}}]},
                {"name": {"cont": "J"}},
            ]
        }
    )
    compiled = str(builder.query.compile(compile_kwargs={"literal_binds": True}))
    # (age > 18 OR age = 18) AND name contains 'J'
    assert '"user".age > 18' in compiled or '"user".age >= 19' in compiled
    assert '"user".age = 18' in compiled
    assert " OR " in compiled
    assert " AND " in compiled
    assert "LIKE '%' || 'J' || '%'" in compiled


# ================================
# Test cases for sort
# ================================
def test_sort() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    query_builder.apply_sort(["-age"])
    expected_query = (
        select(User.id, User.name, Post.id, Post.title)
        .join(Post)
        .order_by(desc(User.age))
    )
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_sort_expliscit_asc() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    query_builder.apply_sort(["+age"])
    expected_query = (
        select(User.id, User.name, Post.id, Post.title).join(Post).order_by(User.age)  # type: ignore
    )
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_sort_with_nested_fields() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    query_builder.apply_sort(["-posts.title"])
    expected_query = (
        select(User.id, User.name, Post.id, Post.title)
        .join(Post)
        .order_by(desc(Post.title))
    )
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_sort_with_invalid_nested_field() -> None:
    """Test sorting with invalid nested field."""
    builder = QueryBuilder(User)
    builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    with pytest.raises(AttributeError):
        builder.apply_sort(["posts.invalid_field"])


def test_sort_with_invalid_relationship() -> None:
    """Test sorting with invalid relationship."""
    builder = QueryBuilder(User)
    builder.apply_select(["id", "name"])
    with pytest.raises(AttributeError):
        builder.apply_sort(["invalid_relationship.field"])


# ================================
# Test cases for limit
# ================================
def test_limit() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    query_builder.apply_limit(10)
    expected_query = (
        select(User.id, User.name, Post.id, Post.title).join(Post).limit(10)
    )
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_sort_with_custom_value_order() -> None:
    """Sort using custom value order via CASE expression."""
    qb = QueryBuilder(User)
    qb.apply_select(["id", "name"]).apply_sort([{"name": ["Zoe", "Alice", "Bob"]}])

    # Expected CASE ordering
    expected = select(User.id, User.name).order_by(
        case(
            {User.name == "Zoe": 0, User.name == "Alice": 1, User.name == "Bob": 2},
            else_=4,
        )
    )
    assert str(qb.query.compile(compile_kwargs={"literal_binds": True})) == str(
        expected.compile(compile_kwargs={"literal_binds": True})
    )


def test_limit_with_negative_value() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    query_builder.apply_limit(-10)
    expected_query = (
        select(User.id, User.name, Post.id, Post.title).join(Post).limit(10)
    )
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


# ================================
# Test cases for offset
# ================================
def test_offset() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    query_builder.apply_offset(10)
    expected_query = (
        select(User.id, User.name, Post.id, Post.title).join(Post).offset(10)
    )
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


def test_offset_with_negative_value() -> None:
    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    query_builder.apply_offset(-10)
    expected_query = (
        select(User.id, User.name, Post.id, Post.title).join(Post).offset(0)
    )
    assert str(
        query_builder.query.compile(compile_kwargs={"literal_binds": True})
    ) == str(expected_query.compile(compile_kwargs={"literal_binds": True}))


# ================================
# Test cases for exec
# ================================
def test_exec(db: Session) -> None:
    post1 = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    post2 = Post(id=2, title="Post 2", content="Content 2", user_id=2)
    user1 = User(
        id=1,
        name="John",
        is_active=True,
        email="john@example.com",
        age=30,
        posts=[post1],
    )
    user2 = User(
        id=2,
        name="Jane",
        is_active=True,
        email="jane@example.com",
        age=25,
        posts=[post2],
    )

    db.add(post1)
    db.add(post2)
    db.add(user1)
    db.add(user2)

    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    results = query_builder.exec(db)
    assert results == [
        (1, "John", 1, "Post 1"),
        (2, "Jane", 2, "Post 2"),
    ]


# ================================
# Test cases for fetch
# ================================
def test_fetch(db: Session) -> None:
    post1 = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    post2 = Post(id=2, title="Post 2", content="Content 2", user_id=2)
    user1 = User(
        id=1,
        name="John",
        is_active=True,
        email="john@example.com",
        age=30,
        posts=[post1],
    )
    user2 = User(
        id=2,
        name="Jane",
        is_active=True,
        email="jane@example.com",
        age=25,
        posts=[post2],
    )

    db.add(post1)
    db.add(post2)
    db.add(user1)
    db.add(user2)

    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    results: list[User] = query_builder.fetch(db, User)

    assert len(results) == 2

    reconstructed_user1 = results[0]
    assert isinstance(reconstructed_user1, User)

    # Verify that the selected fields are present and correct
    user_data = reconstructed_user1.model_dump()
    assert "id" in user_data
    assert "name" in user_data
    assert user_data["id"] == 1
    assert user_data["name"] == "John"
    assert len(reconstructed_user1.posts) == 1
    assert isinstance(reconstructed_user1.posts[0], Post)

    # Verify that the selected post fields are present and correct
    post_data = reconstructed_user1.posts[0].model_dump()
    assert "id" in post_data
    assert "title" in post_data
    assert post_data["id"] == 1
    assert post_data["title"] == "Post 1"

    reconstructed_user2 = results[1]
    assert isinstance(reconstructed_user2, User)

    # Verify that the selected fields are present and correct for user2
    user2_data = reconstructed_user2.model_dump()
    assert "id" in user2_data
    assert "name" in user2_data
    assert user2_data["id"] == 2
    assert user2_data["name"] == "Jane"
    assert len(reconstructed_user2.posts) == 1
    assert isinstance(reconstructed_user2.posts[0], Post)

    # Verify that the selected post fields are present and correct for user2
    post2_data = reconstructed_user2.posts[0].model_dump()
    assert "id" in post2_data
    assert "title" in post2_data
    assert post2_data["id"] == 2
    assert post2_data["title"] == "Post 2"


def test_query_builder_filter_with_nested_fields() -> None:
    """Test filtering with nested fields using dot notation."""
    builder = QueryBuilder(User)
    builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    builder.apply_filter({"posts.title": {"cont": "Python"}})
    query = builder.query

    # The query should include a join with the posts table
    compiled_query = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "JOIN post" in compiled_query
    assert "post.title LIKE '%' || 'Python' || '%'" in compiled_query


def test_query_builder_filter_with_multiple_nested_fields() -> None:
    """Test filtering with multiple nested fields."""
    builder = QueryBuilder(User)
    builder.apply_select(["id", "name", {"posts": ["id", "title", "content"]}])
    builder.apply_filter(
        {"posts.title": {"cont": "Python"}, "posts.content": {"cont": "tutorial"}}
    )
    query = builder.query

    compiled_query = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "JOIN post" in compiled_query
    assert "post.title LIKE '%' || 'Python' || '%'" in compiled_query
    assert "post.content LIKE '%' || 'tutorial' || '%'" in compiled_query


def test_query_builder_filter_with_direct_and_nested_fields() -> None:
    """Test filtering with both direct and nested fields."""
    builder = QueryBuilder(User)
    builder.apply_select(["id", "name", "age", {"posts": ["id", "title"]}])
    builder.apply_filter({"age": {"gt": 18}, "posts.title": {"cont": "Python"}})
    query = builder.query

    compiled_query = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "JOIN post" in compiled_query
    assert '"user".age > 18' in compiled_query
    assert "post.title LIKE '%' || 'Python' || '%'" in compiled_query


def test_query_builder_filter_with_multiple_operators() -> None:
    """Test filtering with multiple operators on the same field."""
    builder = QueryBuilder(User)
    builder.apply_select(["id", "name", "age", {"posts": ["id", "title"]}])
    builder.apply_filter(
        {
            "age": {"gt": 18, "lt": 30},
            "posts.title": {"cont": "Python", "starts_with": "Learn"},
        }
    )
    query = builder.query

    compiled_query = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "JOIN post" in compiled_query
    assert '"user".age > 18' in compiled_query
    assert '"user".age < 30' in compiled_query
    assert "post.title LIKE '%' || 'Python' || '%'" in compiled_query
    assert "post.title LIKE 'Learn' || '%'" in compiled_query


def test_select_with_invalid_field() -> None:
    """Test _select method with invalid field."""
    builder = QueryBuilder(User)
    with pytest.raises(AttributeError):
        builder._select(User, ["invalid_field"])


def test_select_with_invalid_relationship() -> None:
    """Test _select method with invalid relationship."""
    builder = QueryBuilder(User)
    result = builder._select(User, [{"invalid_relationship": ["field"]}])
    assert len(result[0]) == 0
    assert len(result[1]) == 0


def test_select_with_invalid_relationship_fields() -> None:
    """Test _select method with invalid relationship fields."""
    builder = QueryBuilder(User)
    with pytest.raises(AttributeError):
        builder._select(User, [{"posts": ["invalid_field"]}])


def test_build_with_invalid_select() -> None:
    """Test build method with invalid select fields."""
    builder = QueryBuilder(User)
    with pytest.raises(AttributeError):
        builder.build(select=["invalid_field"])


def test_build_with_invalid_filter() -> None:
    """Test build method with invalid filter."""
    builder = QueryBuilder(User)
    with pytest.raises(AttributeError):
        builder.build(filter={"invalid_field": {"eq": "test"}})


def test_build_with_invalid_sort() -> None:
    """Test build method with invalid sort field."""
    builder = QueryBuilder(User)
    with pytest.raises(AttributeError):
        builder.build(sort=["invalid_field"])


def test_build_with_invalid_limit() -> None:
    """Test build method with invalid limit."""
    builder = QueryBuilder(User)
    result = builder.build(limit=-1)
    assert result is not None


def test_build_with_invalid_offset() -> None:
    """Test build method with invalid offset."""
    builder = QueryBuilder(User)
    result = builder.build(offset=-1)
    assert result is not None


def test_reconstruct_objects_with_empty_results() -> None:
    """Test reconstruct_objects method with empty results."""
    builder = QueryBuilder(User)
    result = builder.reconstruct_objects([], User)
    assert result == []


def test_reconstruct_object_with_invalid_relationship() -> None:
    """Test reconstruct_object with invalid relationship."""
    builder = QueryBuilder(User)
    with pytest.raises(KeyError):
        builder.reconstruct_object(User, [{"invalid_relationship": ["field"]}], (), [0])


def test_relationship_types(db: Session) -> None:
    """Test that both to-one and to-many relationships are handled correctly."""
    # Create test data
    user = User(id=1, name="John", is_active=True, email="john@example.com", age=30)
    post1 = Post(id=1, title="Post 1", content="Content 1", user_id=user.id)
    post2 = Post(id=2, title="Post 2", content="Content 2", user_id=user.id)
    user.posts = [post1, post2]
    db.add(post1)
    db.add(post2)
    db.add(user)
    db.commit()
    db.refresh(user)

    # Test querying from User side (one-to-many)
    user_builder = QueryBuilder(User)
    user_results = user_builder.apply_select(
        ["id", "name", {"posts": ["id", "title"]}]
    ).fetch(db, User)

    assert len(user_results) == 1
    assert isinstance(user_results[0].posts, list)
    assert len(user_results[0].posts) == 2
    assert user_results[0].posts[0].title in ["Post 1", "Post 2"]
    assert user_results[0].posts[1].title in ["Post 1", "Post 2"]

    # Test querying from Post side (many-to-one)
    post_builder = QueryBuilder(Post)
    post_results = post_builder.apply_select(
        ["id", "title", {"user": ["id", "name"]}]
    ).fetch(db, Post)

    assert len(post_results) == 2
    for post in post_results:
        assert not isinstance(post.user, list)  # type: ignore
        assert post.user.name == "John"


async def test_exec_async(async_db: AsyncSession) -> None:
    post1 = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    post2 = Post(id=2, title="Post 2", content="Content 2", user_id=2)
    user1 = User(
        id=1,
        name="John",
        is_active=True,
        email="john@example.com",
        age=30,
        posts=[post1],
    )
    user2 = User(
        id=2,
        name="Jane",
        is_active=True,
        email="jane@example.com",
        age=25,
        posts=[post2],
    )

    async_db.add(post1)
    async_db.add(post2)
    async_db.add(user1)
    async_db.add(user2)
    await async_db.commit()

    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    results = await query_builder.exec_async(async_db)
    assert results == [
        (1, "John", 1, "Post 1"),
        (2, "Jane", 2, "Post 2"),
    ]


# ================================
# Test cases for serialization
# ================================
def test_serialize_simple_object(db: Session) -> None:
    """Test serialization of a simple object with direct fields."""
    user = User(id=1, name="John", is_active=True, email="john@example.com", age=30)
    db.add(user)
    db.commit()
    db.refresh(user)

    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name"])
    results = query_builder.fetch(db, User)

    result = query_builder.serialize(results)
    assert len(result) == 1
    assert result[0] == {"id": 1, "name": "John"}


def test_serialize_with_relationships(db: Session) -> None:
    """Test serialization of an object with relationships."""
    post = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    user = User(
        id=1,
        name="John",
        is_active=True,
        email="john@example.com",
        age=30,
        posts=[post],
    )
    db.add(post)
    db.add(user)
    db.commit()
    db.refresh(user)

    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    results = query_builder.fetch(db, User)

    result = query_builder.serialize(results)
    assert len(result) == 1
    assert result[0] == {
        "id": 1,
        "name": "John",
        "posts": [{"id": 1, "title": "Post 1"}],
    }


def test_serialize_with_non_list_relationships(db: Session) -> None:
    """Test serialization of an object with non-list relationships."""
    post = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    user = User(
        id=1,
        name="John",
        is_active=True,
        email="john@example.com",
        age=30,
        posts=[post],
    )
    db.add(post)
    db.add(user)
    db.commit()
    db.refresh(user)

    query_builder = QueryBuilder(model=Post)
    query_builder.apply_select(["id", "title", {"user": ["id", "name"]}])
    results = query_builder.fetch(db, Post)

    result = query_builder.serialize(results)
    assert len(result) == 1
    assert result[0] == {
        "id": 1,
        "title": "Post 1",
        "user": {"id": 1, "name": "John"},
    }


def test_serialize_with_wildcard_fields(db: Session) -> None:
    """Ensure wildcard select returns all model fields."""
    user = User(
        id=1,
        name="John",
        is_active=True,
        email="john@example.com",
        age=30,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["*"])
    results = query_builder.fetch(db, User)

    result = query_builder.serialize(results)
    assert len(result) == 1

    # Check that all expected fields are present with correct values
    user_result = result[0]
    assert user_result["id"] == 1
    assert user_result["name"] == "John"
    assert user_result["email"] == "john@example.com"
    assert user_result["age"] == 30
    assert user_result["is_active"] is True

    # Verify that additional fields are present (they should have default/None values)
    assert "created_at" in user_result
    assert "birth_date" in user_result
    assert "last_login" in user_result


def test_serialize_with_wildcard_relationship(db: Session) -> None:
    """Ensure wildcard select expands relationship fields."""
    post = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    user = User(
        id=1,
        name="John",
        is_active=True,
        email="john@example.com",
        age=30,
        posts=[post],
    )
    db.add(post)
    db.add(user)
    db.commit()
    db.refresh(user)

    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["*", {"posts": ["*"]}])
    results = query_builder.fetch(db, User)

    result = query_builder.serialize(results)
    assert len(result) == 1

    # Check that all expected fields are present with correct values
    user_result = result[0]
    assert user_result["id"] == 1
    assert user_result["name"] == "John"
    assert user_result["email"] == "john@example.com"
    assert user_result["age"] == 30
    assert user_result["is_active"] is True

    # Verify that additional user fields are present
    assert "created_at" in user_result
    assert "birth_date" in user_result
    assert "last_login" in user_result

    # Check posts relationship
    assert "posts" in user_result
    assert len(user_result["posts"]) == 1

    post_result = user_result["posts"][0]
    assert post_result["id"] == 1
    assert post_result["title"] == "Post 1"
    assert post_result["content"] == "Content 1"
    assert post_result["user_id"] == 1

    # Verify that additional post fields are present
    assert "created_at" in post_result
    assert "published_at" in post_result


async def test_serialize_simple_object_async(async_db: AsyncSession) -> None:
    """Test serialization of a simple object with direct fields."""
    user = User(id=1, name="John", is_active=True, email="john@example.com", age=30)
    async_db.add(user)
    await async_db.commit()

    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name"])
    results = await query_builder.fetch_async(async_db, User)

    result = query_builder.serialize(results)
    assert len(result) == 1
    assert result[0] == {"id": 1, "name": "John"}


async def test_serialize_with_relationships_async(async_db: AsyncSession) -> None:
    """Test serialization of an object with relationships."""
    post = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    user = User(
        id=1,
        name="John",
        is_active=True,
        email="john@example.com",
        age=30,
        posts=[post],
    )
    async_db.add(post)
    async_db.add(user)
    await async_db.commit()

    query_builder = QueryBuilder(model=User)
    query_builder.apply_select(["id", "name", {"posts": ["id", "title"]}])
    results = await query_builder.fetch_async(async_db, User)

    result = query_builder.serialize(results)
    assert len(result) == 1
    assert result[0] == {
        "id": 1,
        "name": "John",
        "posts": [{"id": 1, "title": "Post 1"}],
    }


async def test_serialize_with_non_list_relationships_async(
    async_db: AsyncSession,
) -> None:
    """Test serialization of an object with non-list relationships."""
    post = Post(id=1, title="Post 1", content="Content 1", user_id=1)
    user = User(
        id=1,
        name="John",
        is_active=True,
        email="john@example.com",
        age=30,
        posts=[post],
    )
    async_db.add(post)
    async_db.add(user)
    await async_db.commit()

    query_builder = QueryBuilder(model=Post)
    query_builder.apply_select(["id", "title", {"user": ["id", "name"]}])
    results = await query_builder.fetch_async(async_db, Post)

    result = query_builder.serialize(results)
    assert len(result) == 1
    assert result[0] == {
        "id": 1,
        "title": "Post 1",
        "user": {"id": 1, "name": "John"},
    }
