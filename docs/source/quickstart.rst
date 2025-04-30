Quickstart
=========

QueryMate is a powerful query builder for FastAPI and SQLModel that provides a flexible interface for building and executing database queries with support for filtering, sorting, pagination, and field selection. It includes built-in serialization capabilities to transform query results into dictionaries containing only the requested fields.

Installation
-----------

.. code-block:: bash

    pip install querymate

Basic Usage
----------

1. Define your models:

   .. code-block:: python

       class User(SQLModel, table=True):
           id: int = Field(primary_key=True)
           name: str
           posts: list["Post"] = Relationship(back_populates="author")

       class Post(SQLModel, table=True):
           id: int = Field(primary_key=True)
           title: str
           author_id: int = Field(foreign_key="user.id")
           author: User = Relationship(back_populates="posts")

2. Query with relationships:

   .. code-block:: text

       # Select user fields and related post fields (returns serialized results)
       /users?q={"fields":["id","name",{"posts":["title"]}]}

       # Filter by related field
       /users?q={"q":{"posts.title":{"cont":"Python"}}}

       # Sort by related field
       /users?q={"sort":["posts.title"]}

3. Using the QueryMate class:

   .. code-block:: python

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

Serialization
------------

QueryMate automatically serializes query results into dictionaries containing only the requested fields. This helps reduce payload size and improve performance. The serialization process supports:

* Direct field selection
* Nested relationships
* Both list and non-list relationships
* Automatic handling of null values

For raw model instances, use the `run_raw` or `run_raw_async` methods instead.

Next Steps
---------

- Read the :doc:`usage/index` guide for detailed information
- Check out the :doc:`examples/index` for more complex scenarios
- Review the :doc:`api/index` for complete API reference 