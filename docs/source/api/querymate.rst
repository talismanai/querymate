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

Return pagination metadata
~~~~~~~~~~~~~~~~~~~~~~~~~~

`run` can optionally return structured pagination metadata along with items. You can enable it via the query payload or force it via method parameter.

.. code-block:: python

    # Option 1: force via method call
    results = querymate.run(db, User, force_pagination=True)
    # Option 2: respect the query flag
    querymate = Querymate(include_pagination=True)
    results = querymate.run(db, User)  # will include pagination

    # Response shape:
    # {
    #   "items": [{"id": 1, "name": "John"}, ...],
    #   "pagination": {
    #       "total": 57,          # total matching records (ignores limit/offset)
    #       "page": 2,            # current page number (1-based)
    #       "size": 10,           # requested page size (limit)
    #       "pages": 6,           # total pages (ceil(total/size), minimum 1)
    #       "previous_page": 1,   # previous page number or None
    #       "next_page": 3        # next page number or None
    #   }
    # }

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

Return pagination metadata (async)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The async variant also supports returning pagination data.

.. code-block:: python

    async def get_users():
        # Force
        result = await querymate.run_async(db, User, force_pagination=True)
        # Or respect query flag
        result2 = await Querymate(include_pagination=True).run_async(db, User)
        # Same shape as the sync variant:
        # {
        #   "items": [...],
        #   "pagination": {"total": ..., "page": ..., "size": ..., "pages": ..., "previous_page": ..., "next_page": ...}
        # }

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

Custom Value Order Sorting
~~~~~~~~~~~~~~~~~~~~~~~~~~

You can define an explicit order for values of a field. Values listed appear first in the given order; others are ordered later.

.. code-block:: python

    # Bring certain status values first
    querymate = Querymate(
        sort=[{"status": ["pending", "active", "inactive"]}]
    )
    results = querymate.run(db, Ticket)

    # Combine with secondary sort
    querymate = Querymate(
        sort=[{"status": ["pending", "active", "inactive"]}, "-created_at"]
    )
    results = querymate.run(db, Ticket)

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
