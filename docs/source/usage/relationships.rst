Relationships
============

QueryMate provides comprehensive support for handling relationships between models, allowing you to query, filter, and sort by related fields.

Defining Relationships
-------------------

First, define your models with relationships using SQLModel:

.. code-block:: python

    from sqlmodel import SQLModel, Field, Relationship

    class User(SQLModel, table=True):
        id: int = Field(primary_key=True)
        name: str
        posts: list["Post"] = Relationship(back_populates="author")

    class Post(SQLModel, table=True):
        id: int = Field(primary_key=True)
        title: str
        author_id: int = Field(foreign_key="user.id")
        author: User = Relationship(back_populates="posts")

Querying Related Fields
--------------------

You can include related fields in your queries using nested field selection:

.. code-block:: text

    /users?q={"select":["id","name",{"posts":["title"]}]}

Filtering by Related Fields
------------------------

Filter records based on related field values:

.. code-block:: text

    /users?q={"filter":{"posts.title":{"cont":"Python"}}}

Sorting by Related Fields
----------------------

Sort results using related field values:

.. code-block:: text

    /users?q={"sort":["posts.title"]}

Nested Relationships
-----------------

QueryMate supports multiple levels of relationships:

.. code-block:: text

    /users?q={"select":["id",{"posts":["title",{"comments":["content"]}]}]}

Best Practices
------------

* Use appropriate indexes for relationship fields
* Be mindful of N+1 query problems
* Consider the depth of relationship chains
* Document relationship fields in API documentation
* Use eager loading when appropriate 

Excluding Related Items
-----------------------

You can exclude related items based on their status (or any field) by using relationship filters.
Because QueryMate performs an inner join for selected relationships, this will filter the joined
rows while keeping the root records that still have at least one matching related row.

Example: include only posts with status = ``published`` (i.e., exclude any non-published posts):

.. code-block:: text

    /users?q={
      "select": ["id", "name", {"posts": ["id", "title", "status"]}],
      "filter": {"posts.status": {"eq": "published"}}
    }

Example: exclude posts where status is not equal to ``archived`` (i.e., keep all except archived):

.. code-block:: text

    /users?q={
      "select": ["id", "name", {"posts": ["id", "title", "status"]}],
      "filter": {"posts.status": {"ne": "archived"}}
    }

Notes:

- By default, QueryMate uses inner joins for relationships. Root records without
  matching related rows will not be returned.
- Use ``join_type="left"`` to include root records even when they have no related items
  (they will have an empty list for the relationship field).
- Combine with other operators like ``in``/``nin`` for multiple statuses.

Python usage is equivalent when constructing queries programmatically:

.. code-block:: python

    qm = Querymate(
        select=["id", "name", {"posts": ["id", "title", "status"]}],
        filter={"posts.status": {"ne": "archived"}},
    )
    results = qm.run(db, User)

Join Types
----------

By default, QueryMate uses **inner joins** for relationships, excluding parent records
that have no children. Use ``join_type`` to change this behavior:

.. code-block:: text

    # Include users even if they have no posts (posts will be empty list)
    /users?q={"select":["id","name",{"posts":["title"]}],"join_type":"left"}

Available options:

- ``inner`` (default): Excludes parent records without children
- ``left`` or ``outer``: Includes all parent records; children will be ``[]`` if none exist

Python usage:

.. code-block:: python

    # Inner join (default) - only users with posts
    qm = Querymate(
        select=["id", "name", {"posts": ["title"]}],
    )
    results = qm.run(db, User)

    # Left join - all users, posts=[] for those without
    qm = Querymate(
        select=["id", "name", {"posts": ["title"]}],
        join_type="left",
    )
    results = qm.run(db, User)
