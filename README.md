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
    # Returns serialized results (dictionaries)
    return query.run(db, User)

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
    # Returns serialized results (dictionaries)
    return await query.run_async(db, User)

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
Enable it via the query flag or force it via the method parameter:

```python
# Force via method
result = query.run(db, User, force_pagination=True)
# Or async:
# result = await query.run_async(db, User, force_pagination=True)

# Respect the query flag / instance setting
result2 = Querymate(include_pagination=True).run(db, User)

# Response shape
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

Query flag name and default behavior are configurable (see settings):

- `PAGINATION_PARAM_NAME` (default: `include_pagination`)
- `DEFAULT_RETURN_PAGINATION` (default: `False`)

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

Note: QueryMate currently uses inner joins for relationships. Root rows without any matching related rows will be filtered out. If you need to include root rows with an empty related list, left outer joins are not yet configurable.

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
