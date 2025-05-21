QueryMate Class
==============

The QueryMate class provides a powerful interface for building and executing database queries with support for filtering, sorting, pagination, and field selection.

Basic Usage
----------

.. code-block:: python

    from querymate import Querymate
    from sqlmodel import Session, SQLModel

    # Create a QueryMate instance
    querymate = Querymate(
        select=["id", "name"],
        filter={"age": {"gt": 25}},
        sort=["-age"],
        limit=10,
        offset=0
    )

    # Execute the query
    results = querymate.run(db, User)

Class Methods
------------

from_qs
~~~~~~~

Convert native FastAPI QueryParams to a QueryMate instance.

.. code-block:: python

    from fastapi import Request
    from querymate import Querymate

    @app.get("/users")
    def get_users(request: Request):
        querymate = Querymate.from_qs(request.query_params)
        return querymate.run(db, User)

    # Example query:
    # /users?q={"filter":{"age":{"gt":25}},"sort":["-name"],"limit":10}

from_query_param
~~~~~~~~~~~~~~

Convert a query parameter string to a QueryMate instance.

.. code-block:: python

    query_param = '{"filter":{"age":{"gt":25}},"sort":["-name"]}'
    querymate = Querymate.from_query_param(query_param)

fastapi_dependency
~~~~~~~~~~~~~~~~

FastAPI dependency for creating a QueryMate instance from a request.

.. code-block:: python

    from fastapi import Depends
    from querymate import Querymate

    @app.get("/users")
    def get_users(query: Querymate = Depends(Querymate.fastapi_dependency)):
        return query.run(db, User)

Instance Methods
--------------

to_qs
~~~~~

Convert the QueryMate instance to a query string.

.. code-block:: python

    querymate = Querymate(
        select=["id", "name"],
        filter={"age": {"gt": 25}}
    )
    query_string = querymate.to_qs()
    # Returns: q={"select":["id","name"],"filter":{"age":{"gt":25}}}

to_query_param
~~~~~~~~~~~~

Convert the QueryMate instance to a query parameter string.

.. code-block:: python

    querymate = Querymate(
        select=["id", "name"],
        filter={"age": {"gt": 25}}
    )
    query_param = querymate.to_query_param()
    # Returns: {"select":["id","name"],"filter":{"age":{"gt":25}}}

run
~~~

Build and execute the query, returning serialized results.

.. code-block:: python

    # Basic usage
    results = querymate.run(db, User)
    # Returns: [{"id": 1, "name": "John"}, ...]

    # With relationships
    querymate = Querymate(
        select=["id", "name", {"posts": ["id", "title"]}]
    )
    results = querymate.run(db, User)
    # Returns: [{"id": 1, "name": "John", "posts": [{"id": 1, "title": "Post 1"}]}, ...]

run_raw
~~~~~~~

Build and execute the query, returning raw model instances.

.. code-block:: python

    results = querymate.run_raw(db, User)
    # Returns: [<User object>, ...]

run_async
~~~~~~~~

Build and execute the query asynchronously, returning serialized results.

.. code-block:: python

    async def get_users():
        results = await querymate.run_async(db, User)
        # Returns: [{"id": 1, "name": "John"}, ...]

run_raw_async
~~~~~~~~~~~~

Build and execute the query asynchronously, returning raw model instances.

.. code-block:: python

    async def get_users():
        results = await querymate.run_raw_async(db, User)
        # Returns: [<User object>, ...]

Advanced Examples
---------------

Nested Filters
~~~~~~~~~~~~~

.. code-block:: python

    # Filter by related field
    querymate = Querymate(
        filter={"posts.title": {"cont": "Python"}, "age": {"gt": 18}}
    )
    results = querymate.run(db, User)

Complex Sorting
~~~~~~~~~~~~~

.. code-block:: python

    # Sort by multiple fields
    querymate = Querymate(
        sort=["-age", "name"]
    )
    results = querymate.run(db, User)

Field Selection with Relationships
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Select specific fields from related models
    querymate = Querymate(
        select=["id", "name", {"posts": ["id", "title"]}]
    )
    results = querymate.run(db, User)

Pagination
~~~~~~~~~

.. code-block:: python

    # Get second page of results
    querymate = Querymate(
        limit=10,
        offset=10
    )
    results = querymate.run(db, User) 