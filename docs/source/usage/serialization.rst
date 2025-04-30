Serialization
============

QueryMate includes built-in serialization capabilities that transform query results into dictionaries containing only the requested fields. This helps reduce payload size and improve performance.

Overview
--------

Serialization in QueryMate works automatically when using the ``run`` or ``run_async`` methods. These methods return serialized dictionaries containing only the requested fields. For raw model instances, use the ``run_raw`` or ``run_raw_async`` methods instead.

Features
--------

Direct Field Selection
~~~~~~~~~~~~~~~~~~~~

Select specific fields to include in the serialized output:

.. code-block:: python

    # Returns serialized results with only the requested fields
    results = query.run(db, User)
    # [
    #     {
    #         "id": 1,
    #         "name": "John"
    #     }
    # ]

Nested Relationships
~~~~~~~~~~~~~~~~~~

Serialize related models with their own field selection:

.. code-block:: python

    # Returns serialized results with nested relationships
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

List and Non-list Relationships
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

QueryMate handles both list and non-list relationships automatically:

.. code-block:: python

    # List relationship (one-to-many)
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

    # Non-list relationship (many-to-one)
    results = query.run(db, Post)
    # [
    #     {
    #         "id": 1,
    #         "title": "Post 1",
    #         "author": {"id": 1, "name": "John"}
    #     }
    # ]

Null Value Handling
~~~~~~~~~~~~~~~~~

QueryMate automatically handles null values in relationships:

.. code-block:: python

    # Returns null for missing relationships
    results = query.run(db, Post)
    # [
    #     {
    #         "id": 1,
    #         "title": "Post 1",
    #         "author": null  # If author is not set
    #     }
    # ]

Usage Examples
-------------

Basic Serialization
~~~~~~~~~~~~~~~~~

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

Async Serialization
~~~~~~~~~~~~~~~~~

.. code-block:: python

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

Query Parameters
--------------

You can control serialization through query parameters:

.. code-block:: text

    # Select specific fields
    /users?q={"fields":["id","name"]}

    # Select fields with relationships
    /users?q={"fields":["id","name",{"posts":["title"]}]}

    # Complex selection with multiple relationships
    /users?q={"fields":["id","name",{"posts":["title",{"comments":["content"]}]}]}

Best Practices
------------

* Use serialization to reduce payload size and improve performance
* Be mindful of relationship depth to avoid excessive data loading
* Consider creating predefined field sets for common use cases
* Use raw model instances when you need full model functionality
* Document the available fields and relationships for each endpoint 