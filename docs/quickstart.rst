Quickstart
==========

Installation
-----------

.. code-block:: bash

    pip install querymate

Basic Usage
----------

1. Define your SQLModel:

.. code-block:: python

    from sqlmodel import SQLModel, Field

    class User(SQLModel, table=True):
        id: int = Field(primary_key=True)
        name: str
        email: str
        age: int

2. Use QueryMate in your FastAPI route:

.. code-block:: python

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

Advanced Usage
-------------

QueryMate supports various query parameters:

.. code-block:: python

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

Features
--------

- **Filtering**: Build complex filters with a simple interface
- **Sorting**: Sort results by multiple fields
- **Pagination**: Limit and offset support for efficient data retrieval
- **Field Selection**: Select specific fields to return
- **Query Building**: Build SQL queries programmatically