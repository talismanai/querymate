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
   serialization
   predicates

Basic Usage
----------

The basic usage of QueryMate involves three main steps:

1. Define your SQLModel
2. Set up the FastAPI dependency
3. Use QueryMate in your route

Here's a complete example:

.. code-block:: python

    from fastapi import FastAPI, Depends
    from sqlmodel import Session, SQLModel, Field, Relationship
    from querymate import QueryMate

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

    app = FastAPI()

    @app.get("/users")
    async def get_users(
        query: QueryMate = Depends(QueryMate.fastapi_dependency),
        db: Session = Depends(get_db)
    ):
        # Returns serialized results (dictionaries)
        return query.run(db, User)

    @app.get("/users/raw")
    async def get_users_raw(
        query: QueryMate = Depends(QueryMate.fastapi_dependency),
        db: Session = Depends(get_db)
    ):
        # Returns raw model instances
        return query.run_raw(db, User)

Query Parameters
--------------

QueryMate accepts query parameters in JSON format through the ``q`` parameter. The structure is:

.. code-block:: json

    {
        "filter": {
            "field": {"operator": "value"}
        },
        "sort": ["-field1", "field2"],
        "limit": 10,
        "offset": 0,
        "select": ["field1", "field2", {"relationship": ["field1", "field2"]}]
    }

For example:

.. code-block:: text

    /users?q={"filter":{"age":{"gt":18}},"sort":["-name"],"limit":10,"offset":0,"select":["id","name",{"posts":["title"]}]}

Serialization
------------

QueryMate includes built-in serialization capabilities that transform query results into dictionaries containing only the requested fields. This helps reduce payload size and improve performance.

Features:
- Direct field selection
- Nested relationships
- Both list and non-list relationships
- Automatic handling of null values

Example:
.. code-block:: python

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

Default Parameters
---------------

- ``limit``: 10 (max: 200)
- ``offset``: 0
- ``fields``: All fields if not specified
- ``sort``: No sorting if not specified
- ``q``: No filtering if not specified 