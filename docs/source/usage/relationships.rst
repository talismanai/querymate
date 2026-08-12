Relationships
=============

QueryMate provides comprehensive support for handling relationships between models, allowing you to query, filter, and sort by related fields.

Defining Relationships
----------------------

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
-----------------------

You can include related fields in your queries using nested field selection:

.. code-block:: text

    /users?q={"select":["id","name",{"posts":["title"]}]}

Filtering by Related Fields
---------------------------

Filter records based on related field values:

.. code-block:: text

    /users?q={"filter":{"posts.title":{"cont":"Python"}}}

Sorting by Related Fields
-------------------------

Sort results using related field values:

.. code-block:: text

    /users?q={"sort":["posts.title"]}

Nested Relationships
--------------------

QueryMate supports multiple levels of relationships:

.. code-block:: text

    /users?q={"select":["id",{"posts":["title",{"comments":["content"]}]}]}

How relationships are loaded
----------------------------

Selected relationships are loaded with SQLAlchemy's native eager loading:
``selectinload`` for collections and ``joinedload`` for to-one relationships, with
``load_only`` restricting each level to the requested columns. Collections therefore
cost one additional query per relationship - a constant, not one query per parent - and
never multiply the root rows.

That last point is what makes pagination trustworthy: ``limit`` and ``offset`` count
**root records**, whatever relationships you select alongside them, and the ``total`` in
a paginated response is computed over the same set.

Filtering by a relationship
---------------------------

A condition on a related field asks *which root records to return*. It is compiled to a
correlated ``EXISTS``, so it works whether or not the relationship is also selected:

.. code-block:: text

    /users?q={"filter":{"posts.status":{"eq":"published"}}}

That returns the users who have at least one published post. Conditions sharing a
relationship prefix are grouped into a single ``EXISTS``, so:

.. code-block:: text

    /users?q={"filter":{"posts.title":{"cont":"Python"},"posts.status":{"eq":"published"}}}

asks for users with one post that is *both* published and matches the title - not a
published post and, separately, some other post about Python.

Sorting by a related field
--------------------------

Sorting across a relationship uses a correlated aggregate rather than a join, so parents
are never duplicated: ascending sorts by the child's smallest value, descending by its
largest.

.. code-block:: text

    /users?q={"sort":["-posts.title"]}

Choosing which children to load
-------------------------------

A top-level relationship filter picks *parents*. To restrict which *children* are
loaded, put the filter inside the relationship's own node by giving it a
``{"select": ..., "filter": ...}`` object instead of a plain list:

.. code-block:: text

    /users?q={"select":["id","name",{"posts":{"select":["id","title"],"filter":{"status":{"eq":"published"}}}}]}

Every user comes back, each carrying only their published posts - and users with no
published post carry an empty list rather than disappearing.

The two forms compose, and answer different questions:

.. code-block:: text

    # users who have at least one published post, with all of their posts
    {"select":["id",{"posts":["id","title","status"]}],"filter":{"posts.status":{"eq":"published"}}}

    # all users, each with only their published posts
    {"select":["id",{"posts":{"select":["id","title"],"filter":{"status":{"eq":"published"}}}}]}

    # users who have a published post, showing only those posts
    {"select":["id",{"posts":{"select":["id","title"],"filter":{"status":{"eq":"published"}}}}],
     "filter":{"posts.status":{"eq":"published"}}}

Filters inside a relationship node use field names relative to that relationship's
model (``status``, not ``posts.status``) and support the full operator set. They work at
any depth.

.. note::

   Before relationships moved to eager loading, a top-level relationship filter did
   both jobs at once, because the inner join it relied on happened to drop
   non-matching children as a side effect. Selecting parents and narrowing children are
   now separate, so each is expressible on its own.

Python usage is equivalent when constructing queries programmatically:

.. code-block:: python

    # Users who have at least one non-archived post
    qm = Querymate(
        select=["id", "name", {"posts": ["id", "title", "status"]}],
        filter={"posts.status": {"ne": "archived"}},
    )

    # All users, each carrying only their non-archived posts
    qm = Querymate(
        select=[
            "id",
            "name",
            {
                "posts": {
                    "select": ["id", "title", "status"],
                    "filter": {"status": {"ne": "archived"}},
                }
            },
        ],
        join_type="left",
    )
    results = qm.run(db, User)

Join Types
----------

By default, selecting a relationship restricts the results to parents that have at
least one child. Use ``join_type`` to change this behavior:

.. code-block:: text

    # Include users even if they have no posts (posts will be empty list)
    /users?q={"select":["id","name",{"posts":["title"]}],"join_type":"left"}

Available options:

- ``inner`` (default): Excludes parent records without children
- ``left`` or ``outer``: Includes all parent records; children will be ``[]`` if none exist

The name is historical: relationships are no longer loaded with a SQL join, so
``inner`` is applied as an ``EXISTS`` restriction on the parent. The observable
behaviour is unchanged, and unlike a join it neither multiplies rows nor interferes
with ``limit``.

Python usage:

.. code-block:: python

    # Inner (default) - only users with posts
    qm = Querymate(
        select=["id", "name", {"posts": ["title"]}],
    )
    results = qm.run(db, User)

    # Left - all users, posts=[] for those without
    qm = Querymate(
        select=["id", "name", {"posts": ["title"]}],
        join_type="left",
    )
    results = qm.run(db, User)
