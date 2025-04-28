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

    /users?q={"fields":["id","name",{"posts":["title"]}]}

Filtering by Related Fields
------------------------

Filter records based on related field values:

.. code-block:: text

    /users?q={"q":{"posts.title":{"cont":"Python"}}}

Sorting by Related Fields
----------------------

Sort results using related field values:

.. code-block:: text

    /users?q={"sort":["posts.title"]}

Nested Relationships
-----------------

QueryMate supports multiple levels of relationships:

.. code-block:: text

    /users?q={"fields":["id",{"posts":["title",{"comments":["content"]}]}]}

Best Practices
------------

* Use appropriate indexes for relationship fields
* Be mindful of N+1 query problems
* Consider the depth of relationship chains
* Document relationship fields in API documentation
* Use eager loading when appropriate 