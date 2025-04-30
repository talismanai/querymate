Examples
========

This section provides practical examples of using QueryMate in various scenarios.

Basic CRUD Operations
------------------

Here's a complete example of a FastAPI application with CRUD operations using QueryMate:

.. code-block:: python

    from fastapi import FastAPI, Depends, HTTPException
    from sqlmodel import Session, SQLModel, create_engine, Field
    from querymate import QueryMate
    from typing import Optional

    # Models
    class User(SQLModel, table=True):
        id: Optional[int] = Field(default=None, primary_key=True)
        name: str
        email: str
        age: int

    # Database setup
    DATABASE_URL = "sqlite:///./test.db"
    engine = create_engine(DATABASE_URL)
    SQLModel.metadata.create_all(engine)

    def get_db():
        with Session(engine) as session:
            yield session

    app = FastAPI()

    # CRUD endpoints
    @app.get("/users")
    def get_users(
        query: QueryMate = Depends(QueryMate.querymate_dependency),
        db: Session = Depends(get_db)
    ):
        return query.run(db, User)

    @app.get("/users/{user_id}")
    def get_user(user_id: int, db: Session = Depends(get_db)):
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return user

    @app.post("/users")
    def create_user(user: User, db: Session = Depends(get_db)):
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

Complex Filtering
---------------

Example with multiple filters and relationships:

.. code-block:: python

    @app.get("/posts")
    def get_posts(
        query: QueryMate = Depends(QueryMate.querymate_dependency),
        db: Session = Depends(get_db)
    ):
        # Example query:
        # /posts?q={
        #     "filter": {
        #         "title": {"cont": "Python"},
        #         "author.name": {"starts_with": "John"},
        #         "created_at": {"gt": "2024-01-01"}
        #     },
        #     "sort": ["-created_at"],
        #     "limit": 10,
        #     "select": ["id", "title", {"author": ["name"]}]
        # }
        return query.run(db, Post)

Nested Relationships
-----------------

Example with nested relationships and field selection:

.. code-block:: python

    @app.get("/users/{user_id}/posts")
    def get_user_posts(
        user_id: int,
        query: QueryMate = Depends(QueryMate.querymate_dependency),
        db: Session = Depends(get_db)
    ):
        # Example query:
        # /users/1/posts?q={
        #     "select": [
        #         "title",
        #         "content",
        #         {
        #             "comments": [
        #                 "content",
        #                 {"author": ["name"]}
        #             ]
        #         }
        #     ],
        #     "sort": ["-created_at"]
        # }
        query.filter({"author_id": user_id})
        return query.run(db, Post)

Custom Query Builder
-----------------

Example of using the QueryBuilder directly for custom queries:

.. code-block:: python

    from querymate.core.query_builder import QueryBuilder

    @app.get("/custom")
    def custom_query(db: Session = Depends(get_db)):
        builder = QueryBuilder(User)
        query = (
            builder
            .select(["name", "email"])
            .filter({"age": {"gt": 18}})
            .sort(["-name"])
            .limit_and_offset(10, 0)
            .build()
        )
        return builder.fetch(db) 