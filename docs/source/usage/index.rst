Usage Guide
===========

This guide covers the main features and usage patterns of QueryMate.

.. toctree::
   :maxdepth: 2

   filtering
   sorting
   pagination
   field_selection
   relationships

Basic Usage
----------

The basic usage of QueryMate involves three main steps:

1. Define your SQLModel
2. Set up the FastAPI dependency
3. Use QueryMate in your route

Here's a complete example:

.. code-block:: python

    from fastapi import FastAPI, Depends
    from sqlmodel import Session, SQLModel, Field
    from querymate import QueryMate

    class User(SQLModel, table=True):
        id: int = Field(primary_key=True)
        name: str
        email: str
        age: int

    app = FastAPI()

    @app.get("/users")
    async def get_users(
        query: QueryMate = Depends(QueryMate.fastapi_dependency),
        db: Session = Depends(get_db)
    ):
        return query.run(db, User)

Query Parameters
--------------

QueryMate accepts query parameters in JSON format through the ``q`` parameter. The structure is:

.. code-block:: json

    {
        "q": {
            "field": {"operator": "value"}
        },
        "sort": ["-field1", "field2"],
        "limit": 10,
        "offset": 0,
        "fields": ["field1", "field2"]
    }

For example:

.. code-block:: text

    /users?q={"q":{"age":{"gt":18}},"sort":["-name"],"limit":10,"offset":0,"fields":["id","name"]}

Default Parameters
---------------

- ``limit``: 10 (max: 200)
- ``offset``: 0
- ``fields``: All fields if not specified
- ``sort``: No sorting if not specified
- ``q``: No filtering if not specified 