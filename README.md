# 🔍 QueryMate

[![PyPI version](https://badge.fury.io/py/querymate.svg)](https://badge.fury.io/py/querymate)
[![codecov](https://codecov.io/gh/banduk/querymate/graph/badge.svg?token=CXN9YCLMMG)](https://codecov.io/gh/banduk/querymate)
[![Documentation](https://img.shields.io/badge/%F0%9F%93%98-documentation-blue?link=https%3A%2F%2Fbanduk.github.io%2Fquerymate%2F)](https://banduk.github.io/querymate/)
[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**A powerful query builder for FastAPI and SQLModel** — with full support for:

- ✅ Filtering
- ✅ Sorting
- ✅ Pagination (limit/offset)
- ✅ Field selection
- ✅ Grouping (with date granularity and timezone support)
- ✅ Query parameter parsing
- ✅ Async database support
- ✅ Built-in serialization

Built for teams that want to build robust APIs with FastAPI and SQLModel.

---

## ✨ Key Features

| Feature                       | Description                                                                 |
| ----------------------------- | --------------------------------------------------------------------------- |
| 🔍 Query Parameter Parsing     | Parse and validate query parameters with ease                               |
| 🎯 Filtering                  | Build complex filters with a simple interface                               |
| 📊 Sorting                    | Sort results by multiple fields                                            |
| 📄 Pagination                 | Limit and offset support for efficient data retrieval                      |
| 🎨 Field Selection            | Select specific fields to return                                           |
| 🏗️ Query Building             | Build SQL queries programmatically                                         |
| ⚡ Async Support              | Full support for async database operations                                 |
| 📦 Serialization              | Built-in serialization with support for relationships                      |
| 📁 Grouping                   | Group results by field with date granularity and timezone support          |
| 🔐 Authorization Scopes       | Apply your app's access rules to every model a query loads                 |
| 📖 OpenAPI Schema             | Document `q` per model: fields, operators by type, runnable examples       |

---

## 🚀 Quick Start

### Installation

```bash
pip install querymate
```

For async support, you'll also need to install the appropriate async database driver:

```bash
# For SQLite
pip install aiosqlite

# For PostgreSQL
pip install asyncpg

# For MySQL
pip install aiomysql
```

### Basic Usage

1. Define your SQLModel:

```python
from sqlmodel import SQLModel, Field, Relationship

class User(SQLModel, table=True):
    id: int = Field(primary_key=True)
    name: str
    email: str
    age: int
    posts: list["Post"] = Relationship(back_populates="author")

class Post(SQLModel, table=True):
    id: int = Field(primary_key=True)
    title: str
    content: str
    author_id: int = Field(foreign_key="user.id")
    author: User = Relationship(back_populates="posts")
```

2. Use QueryMate in your FastAPI route (Synchronous):

```python
from fastapi import FastAPI, Depends
from sqlmodel import Session
from querymate import QueryMate

app = FastAPI()

@app.get("/users")
def get_users(
    query: QueryMate = Depends(QueryMate.fastapi_dependency),
    db: Session = Depends(get_db)
):
    # Returns serialized results as a list
    return query.run(db, User)

@app.get("/users/paginated")
def get_users_paginated(
    query: QueryMate = Depends(QueryMate.fastapi_dependency),
    db: Session = Depends(get_db)
):
    # Returns items plus pagination metadata
    return query.run_paginated(db, User)

@app.get("/users/raw")
def get_users_raw(
    query: QueryMate = Depends(QueryMate.fastapi_dependency),
    db: Session = Depends(get_db)
):
    # Returns raw model instances
    return query.run_raw(db, User)
```

3. Use QueryMate with Async Database (Asynchronous):

```python
from fastapi import FastAPI, Depends
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker
from querymate import QueryMate

app = FastAPI()

# Create async database engine
engine = create_async_engine("sqlite+aiosqlite:///example.db")

# Create async session factory
async_session = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

# Database dependency
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()

@app.get("/users")
async def get_users(
    query: QueryMate = Depends(QueryMate.fastapi_dependency),
    db: AsyncSession = Depends(get_db)
):
    # Returns serialized results
    return await query.run_async(db, User)

@app.get("/users/paginated")
async def get_users_paginated(
    query: QueryMate = Depends(QueryMate.fastapi_dependency),
    db: AsyncSession = Depends(get_db)
):
    # Returns items plus pagination metadata
    return await query.run_async_paginated(db, User)

@app.get("/users/raw")
async def get_users_raw(
    query: QueryMate = Depends(QueryMate.fastapi_dependency),
    db: AsyncSession = Depends(get_db)
):
    # Returns raw model instances
    return await query.run_raw_async(db, User)
```

### Advanced Usage

```python
# Example query parameters
# ?q={"filter": {"age": {"gt": 18}}, "sort": ["-name", "age"], "limit": 10, "offset": 0, "select": ["id", "name", {"posts": ["title"]}]}

@app.get("/users")
async def get_users(
    query: QueryMate = Depends(QueryMate.fastapi_dependency),
    db: AsyncSession = Depends(get_db)
):
    # The query will be built and executed automatically
    # Results will be serialized according to the fields
    return await query.run_async(db, User)
```

### OpenAPI Documentation

`Depends(QueryMate.fastapi_dependency)` leaves the endpoint with **no query parameters
in Swagger** — the dependency takes the whole `Request`, so FastAPI has nothing typed to
document. `for_model` declares `q` properly and generates a schema from your model:

```python
from querymate import Querymate, Exposed

UsersQuery = Querymate.for_model(
    User,
    exposed=Exposed(fields=["id", "name"], relationships={"posts": None}),
)

@app.get("/users")
def list_users(q: Querymate = Depends(UsersQuery), db: Session = Depends(get_db)):
    return q.run(db)          # for_model binds the model
```

The endpoint now documents its selectable, filterable and sortable fields, the operators
valid for each one (`i_cont` on strings, `gt` on numbers and dates, `true` on booleans),
and examples built from your own field names. `exposed` is enforced, not just
documented — a query naming anything outside it is rejected with a 4xx, so the docs
cannot drift from reality. Omit it to expose the whole model.

Since OpenAPI is static and authorization is per-request, the schema describes what the
endpoint may expose to *someone*; scopes decide what each principal actually sees.

### Authorization Scopes

QueryMate does not implement authorization — it applies the authorization your app
already has. Declare, per model, the condition under which the current principal may
see its rows, and QueryMate injects it into every query that loads that model,
including nested relationships.

Access usually has to be looked up ("is the user on a team that has access?"), so a
scope is a resolver receiving the principal and a live session:

```python
from querymate import ScopeRegistry

scopes = ScopeRegistry()

@scopes.register(Post)
def post_scope(ctx):
    return Post.team_id.in_(
        select(TeamMember.team_id).where(TeamMember.user_id == ctx.principal.id)
    )

@app.get("/users")
def list_users(
    query: QueryMate = Depends(QueryMate.fastapi_dependency),
    db: Session = Depends(get_db),
    me = Depends(get_current_user),
):
    return query.run(db, User, scopes=scopes.bind(principal=me, db=db))
```

Each resolver runs at most once per model per request — never once per row — and
`ctx.cache` lets several models share one expensive lookup. Counts respect scopes, so
`total` never leaks the existence of invisible rows. Querying a model with no
registered scope raises `UnscopedModelError`; mark genuinely public data with
`scopes.allow_all(Model)`, or bind with `strict=False` to adopt scopes gradually.
Omitting `scopes=` leaves behaviour unchanged.

See [the authorization guide](docs/source/usage/authorization.rst) for async
resolvers and the current limits.

### Logical Filters (AND/OR)

Combine conditions explicitly with `and` and `or` in the `filter` block — fully backward compatible with field-based filters:

- OR on the same property (e.g., status = 1 OR status = 2):

  ```text
  /users?q={"filter":{"or":[{"status":{"eq":1}},{"status":{"eq":2}}]}}
  ```

  Or using `in`:

  ```text
  /users?q={"filter":{"status":{"in":[1,2]}}}
  ```

- Mixing AND and OR:

  ```text
  /users?q={
    "filter":{
      "and":[
        {"or":[{"age":{"gt":18}},{"age":{"eq":18}}]},
        {"name":{"cont":"J"}}
      ]
    }
  }
  ```

Direct equality without an operator remains supported, e.g. `{"filter":{"status": 1}}`.

### Sorting

Basic sorting:

```python
# Ascending by name
Querymate(sort=["name"]).run_raw(db, User)

# Descending by age, then ascending by name
Querymate(sort=["-age", "name"]).run_raw(db, User)
```

Custom value order (e.g., status pipelines):

```python
# Bring these status values first in this order; others later
Querymate(sort=[{"status": ["pending", "active", "inactive"]}]).run_raw(db, Ticket)

# Equivalent explicit form
Querymate(sort=[{"status": {"values": ["pending", "active", "inactive"]}}]).run_raw(db, Ticket)

# Combine with secondary sort to order remaining values
Querymate(sort=[{"status": ["pending", "active", "inactive"]}, "-created_at"]).run_raw(db, Ticket)

# Custom order on related field using dot notation
Querymate(sort=[{"posts.visibility": ["private", "internal", "public"]}]).run_raw(db, User)
```

### Pagination Metadata Response

In addition to plain lists, you can include pagination metadata alongside items.
Use the dedicated paginated methods:

```python
# Sync paginated response
result = query.run_paginated(db, User)

# Async paginated response
result = await query.run_async_paginated(db, User)

# Response shape (PaginatedResponse object)
# {
#   "items": [{"id": 1, "name": "John"}, ...],
#   "pagination": {
#     "total": 57,
#     "page": 2,
#     "size": 10,
#     "pages": 6,
#     "previous_page": 1,
#     "next_page": 3
#   }
# }
```

The standard `run` and `run_async` methods always return a plain list of items:

```python
# Always returns a list[dict[str, Any]]
result = query.run(db, User)
```

### Grouping

Group query results by any field, including dates with configurable granularity and timezone support.

#### Basic Grouping by Field

```python
# Group users by status
querymate = Querymate(
    select=["id", "name", "status"],
    group_by="status",
    limit=10,  # Per-group limit
)
result = querymate.run_grouped(db, User)
# Or async:
# result = await querymate.run_grouped_async(db, User)
```

Query parameter example:
```text
/users?q={"select":["id","name","status"],"group_by":"status","limit":10}
```

#### Date Grouping with Granularity

Group by date fields with configurable granularity: `year`, `month`, `day`, `hour`, or `minute`.

```python
# Group by month
querymate = Querymate(
    select=["id", "title", "created_at"],
    group_by={"field": "created_at", "granularity": "month"},
    limit=10,
)
result = querymate.run_grouped(db, Post)
```

Query parameter examples:
```text
# Group by year
/posts?q={"group_by":{"field":"created_at","granularity":"year"}}

# Group by day
/posts?q={"group_by":{"field":"created_at","granularity":"day"}}

# Group by hour
/posts?q={"group_by":{"field":"created_at","granularity":"hour"}}
```

#### Timezone Support

Apply timezone offset to date grouping using numeric offset or IANA timezone names.

```python
# Using numeric offset (UTC-3)
querymate = Querymate(
    select=["id", "title", "created_at"],
    group_by={
        "field": "created_at",
        "granularity": "day",
        "tz_offset": -3
    },
    limit=10,
)

# Using IANA timezone name
querymate = Querymate(
    select=["id", "title", "created_at"],
    group_by={
        "field": "created_at",
        "granularity": "day",
        "timezone": "America/Sao_Paulo"
    },
    limit=10,
)
```

Query parameter examples:
```text
# With numeric offset
/posts?q={"group_by":{"field":"created_at","granularity":"day","tz_offset":-3}}

# With IANA timezone
/posts?q={"group_by":{"field":"created_at","granularity":"day","timezone":"America/Sao_Paulo"}}
```

Supported IANA timezones include: `UTC`, `America/New_York`, `America/Los_Angeles`, `America/Sao_Paulo`, `Europe/London`, `Europe/Paris`, `Asia/Tokyo`, `Asia/Shanghai`, `Australia/Sydney`, and more.

#### Grouped Response Structure

```python
{
    "groups": [
        {
            "key": "active",  # or "2024-01" for month grouping
            "items": [
                {"id": 1, "name": "Alice", "status": "active"},
                {"id": 2, "name": "Bob", "status": "active"}
            ],
            "pagination": {
                "total": 15,
                "page": 1,
                "size": 10,
                "pages": 2,
                "previous_page": null,
                "next_page": 2
            }
        },
        {
            "key": "inactive",
            "items": [...],
            "pagination": {...}
        }
    ],
    "truncated": false  # true if MAX_LIMIT was reached
}
```

#### Pagination Behavior

- `limit` applies **per group** (each group returns up to `limit` items)
- `MAX_LIMIT` (default 200) caps the **total items across all groups combined**
- Groups are ordered naturally: alphabetically for strings, chronologically for dates

```python
# 10 items per group, but total won't exceed MAX_LIMIT (200)
querymate = Querymate(
    select=["id", "name", "status"],
    group_by="status",
    limit=10,
    sort=["-created_at"],  # Sorting applies within each group
)
```

#### Combining with Filters and Sorting

```python
# Group active users by status, sorted by age within each group
querymate = Querymate(
    select=["id", "name", "status", "age"],
    filter={"is_active": True},
    group_by="status",
    sort=["-age"],
    limit=10,
)
result = querymate.run_grouped(db, User)
```

### Serialization

QueryMate includes built-in serialization capabilities that transform query results into dictionaries containing only the requested fields. This helps reduce payload size and improve performance.

Features:
- Direct field selection
- Nested relationships
- Both list and non-list relationships
- Automatic handling of null values

Example:
```python
# Returns serialized results with only the requested fields
results = query.run(db, User)
# [
#     {
#         "id": 1,
#         "name": "John",
#         "posts": [
#             {"id": 1, "title": "Post 1"},
#             {"id": 2, "title": "Post 2"}
#         ]
#     }
# ]

# Returns raw model instances
raw_results = query.run_raw(db, User)
# [User(id=1, name="John", posts=[Post(id=1, title="Post 1"), Post(id=2, title="Post 2")])]
```

### Exclude related items by status

To exclude related rows where a field does not match a value, filter on the related field using dot notation. This filters the joined rows while keeping the root records that still have matching related rows.

```python
# Keep only posts with status == "published"
querymate = Querymate(
    select=["id", "name", {"posts": ["id", "title", "status"]}],
    filter={"posts.status": {"eq": "published"}},
)
results = querymate.run(db, User)

# Exclude posts where status != "archived" (keep all except archived)
querymate = Querymate(
    select=["id", "name", {"posts": ["id", "title", "status"]}],
    filter={"posts.status": {"ne": "archived"}},
)
results = querymate.run(db, User)
```

### Join Types

By default, QueryMate uses inner joins for relationships, excluding root records without matching related rows. Use `join_type` to change this behavior:

```python
# Inner join (default) - only users with posts
querymate = Querymate(
    select=["id", "name", {"posts": ["id", "title"]}],
)
results = querymate.run(db, User)

# Left join - all users, posts=[] for those without
querymate = Querymate(
    select=["id", "name", {"posts": ["id", "title"]}],
    join_type="left",
)
results = querymate.run(db, User)
```

Query parameter example:
```text
/users?q={"select":["id","name",{"posts":["title"]}],"join_type":"left"}
```

Available options:
- `inner` (default): Excludes parent records without children
- `left` or `outer`: Includes all parent records; children will be `[]` if none exist

---

## 🛠️ Development Guide

### Project Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/querymate.git
cd querymate

# Set up the development environment
make setup

# Activate the virtual environment
source .venv/bin/activate
```

### Project Structure

```
querymate/
├── core/                         # Core functionality
│   ├── querymate.py              # Main QueryMate class
│   ├── filter.py                 # Filter handling
│   ├── query_builder.py          # Query building
│   ├── grouping.py               # Grouping functionality
│   └── __init__.py              # Package initialization
├── tests/                        # Test suite
├── docs/                         # Documentation
│   ├── source/                  # Sphinx documentation source
│   │   ├── api/                 # API documentation
│   │   ├── examples/            # Usage examples
│   │   └── usage/               # Usage guides
│   └── conf.py                  # Sphinx configuration
└── examples/                     # Example usage
```

### Development Workflow

1. Create a new feature branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```

2. Make your changes and run tests:
   ```bash
   make test
   ```

3. Run code quality checks:
   ```bash
   make lint
   make format
   python -m mypy .
   ```

4. Update documentation:
   ```bash
   make docs
   ```

5. Submit a pull request

### Testing

```bash
# Run all tests
make test

# Run tests with coverage
python -m pytest --cov=querymate
```

### Documentation

```bash
# Build the documentation
make docs

# View the documentation
open docs/_build/html/index.html
```

---

## 📚 Documentation

For detailed documentation, visit [banduk.github.io/querymate](https://banduk.github.io/querymate).

---

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
