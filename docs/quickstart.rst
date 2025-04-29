Quick Start Guide
===============

This guide will help you get started with QueryMate quickly.

Basic Setup
----------

1. First, install QueryMate:

   .. code-block:: bash

       pip install querymate

2. Define your SQLModel:

   .. code-block:: python

       from sqlmodel import SQLModel, Field

       class User(SQLModel, table=True):
           id: int = Field(primary_key=True)
           name: str
           email: str
           age: int

3. Set up FastAPI with QueryMate:

   .. code-block:: python

       from fastapi import FastAPI, Depends
       from sqlmodel import Session
       from querymate import QueryMate

       app = FastAPI()

       @app.get("/users")
       def get_users(
           query: QueryMate = Depends(QueryMate.querymate_dependency),
           db: Session = Depends(get_db)
       ):
           return query.run(db, User)

Basic Usage
----------

Here are some common query examples:

Filter by age:

.. code-block:: text

    /users?q={"q":{"age":{"gt":18}}}

Sort by name (descending):

.. code-block:: text

    /users?q={"sort":["-name"]}

Paginate results:

.. code-block:: text

    /users?q={"limit":10,"offset":0}

Select specific fields:

.. code-block:: text

    /users?q={"fields":["id","name","email"]}

Combine multiple operations:

.. code-block:: text

    /users?q={"q":{"age":{"gt":18}},"sort":["-name"],"limit":10,"offset":0,"fields":["id","name"]}

Working with Relationships
-----------------------

1. Define models with relationships:

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

       # Select user fields and related post fields
       /users?q={"fields":["id","name",{"posts":["title"]}]}

       # Filter by related field
       /users?q={"q":{"posts.title":{"cont":"Python"}}}

       # Sort by related field
       /users?q={"sort":["posts.title"]}

Next Steps
---------

- Read the :doc:`usage/index` guide for detailed information
- Check out the :doc:`examples/index` for more complex scenarios
- Review the :doc:`api/index` for complete API reference