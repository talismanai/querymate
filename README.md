# 🔍 QueryMate

[![PyPI version](https://badge.fury.io/py/querymate.svg)](https://badge.fury.io/py/querymate)
[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**A powerful query builder for FastAPI and SQLModel** — with full support for:

- ✅ Filtering
- ✅ Sorting
- ✅ Pagination (limit/offset)
- ✅ Field selection
- ✅ Query parameter parsing

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

---

## 🚀 Quick Start

### Installation

```bash
pip install querymate
```

### Basic Usage

1. Define your SQLModel:

```python
from sqlmodel import SQLModel, Field

class User(SQLModel, table=True):
    id: int = Field(primary_key=True)
    name: str
    email: str
    age: int
```

2. Use QueryMate in your FastAPI route:

```python
from fastapi import FastAPI, Depends
from sqlmodel import Session
from querymate import QueryMate

app = FastAPI()

@app.get("/users")
async def get_users(
    query: QueryMate = Depends(QueryMate.querymate_dependency),
    db: Session = Depends(get_db)
):
    return query.run(db, User)
```

### Advanced Usage

```python
# Example query parameters
# ?q={"q": {"age": {"gt": 18}}, "sort": ["-name", "age"], "limit": 10, "offset": 0, "fields": ["id", "name"]}

@app.get("/users")
async def get_users(
    query: QueryMate = Depends(QueryMate.querymate_dependency),
    db: Session = Depends(get_db)
):
    # The query will be built and executed automatically
    # Results will be serialized according to the fields
    return query.run(db, User)
```

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
│   ├── predicate.py              # Predicate handling
│   └── query_builder.py          # Query building
└── tests/                        # Test suite
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
