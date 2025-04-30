Quick Start Guide
===============

This guide will help you get started with QueryMate quickly.

Basic Setup
----------

1. First, install QueryMate:

   .. code-block:: bash

       pip install querymate

   For async support, you'll also need to install the appropriate async database driver:

   .. code-block:: bash

       # For SQLite
       pip install aiosqlite

       # For PostgreSQL
       pip install asyncpg

       # For MySQL
       pip install aiomysql

2. Define your SQLModel:

   .. code-block:: python

       from sqlmodel import SQLModel, Field

       class User(SQLModel, table=True):
           id: int = Field(primary_key=True)
           name: str
           email: str
           age: int

3. Set up FastAPI with QueryMate (Synchronous):

   .. code-block:: python

       from fastapi import FastAPI, Depends
       from sqlmodel import Session
       from querymate import QueryMate

       app = FastAPI()

       @app.get("/users")
       def get_users(
           query: QueryMate = Depends(QueryMate.fastapi_dependency),
           db: Session = Depends(get_db)
       ):
           return query.run(db, User)

4. Set up FastAPI with QueryMate (Asynchronous):

   .. code-block:: python

       from fastapi import FastAPI, Depends
       from sqlmodel.ext.asyncio.session import AsyncSession
       from sqlalchemy.ext.asyncio import create_async_engine
       from sqlalchemy.orm import sessionmaker
       from querymate import QueryMate

       app = FastAPI()

       # Create async database engine
       engine = create_async_engine("sqlite+aiosqlite:///example.db")

       # Create async session factory
       async_session = sessionmaker(
           engine,
           class_=AsyncSession,
           expire_on_commit=False,
           autocommit=False,
           autoflush=False,
       )

       # Database dependency
       async def get_db() -> AsyncGenerator[AsyncSession, None]:
           async with async_session() as session:
               try:
                   yield session
               finally:
                   await session.close()

       @app.get("/users")
       async def get_users(
           query: QueryMate = Depends(QueryMate.fastapi_dependency),
           db: AsyncSession = Depends(get_db)
       ):
           return await query.run_async(db, User)

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