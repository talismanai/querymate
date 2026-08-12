"""End-to-end example: documented, authorized queries.

Shows the three pieces working together:

* ``Querymate.for_model`` declares ``q`` so the endpoint documents itself in Swagger,
  and enforces the surface it advertises.
* ``ScopeRegistry`` applies the application's own access rules to every model a query
  loads, at any depth.
* ``install_exception_handler`` turns a rejected query into a structured 4xx.

Run it with ``uvicorn examples.documented_and_scoped:app`` and open ``/docs``. Pass
``?as_user=1`` (Alice, Acme) or ``?as_user=2`` (Bob, Globex) to see the scope change
what comes back.
"""

from fastapi import Depends, FastAPI, Query
from sqlmodel import (
    Field,
    Relationship,
    Session,
    SQLModel,
    create_engine,
    select,
)
from sqlmodel.pool import StaticPool

from querymate import (
    Exposed,
    Querymate,
    ResourceRegistry,
    ScopeRegistry,
    install_exception_handler,
)


class TeamMember(SQLModel, table=True):  # type: ignore[call-arg]
    id: int = Field(primary_key=True)
    team_id: int
    user_id: int


class User(SQLModel, table=True):  # type: ignore[call-arg]
    id: int = Field(primary_key=True)
    name: str
    email: str
    # Something the API should never hand out, to show that `exposed` governs it.
    hashed_password: str = Field(default="secret")
    posts: list["Post"] = Relationship(back_populates="user")


class Post(SQLModel, table=True):  # type: ignore[call-arg]
    id: int = Field(primary_key=True)
    title: str
    status: str = Field(default="draft")
    team_id: int
    user_id: int = Field(foreign_key="user.id")
    user: User = Relationship(back_populates="posts")


engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
SQLModel.metadata.create_all(engine)


def get_db() -> Session:
    with Session(engine) as session:
        yield session  # type: ignore[misc]


def seed() -> None:
    with Session(engine) as db:
        db.add(User(id=1, name="Alice", email="alice@acme.com"))
        db.add(User(id=2, name="Bob", email="bob@globex.com"))
        db.add(TeamMember(id=1, team_id=1, user_id=1))
        db.add(TeamMember(id=2, team_id=2, user_id=2))
        db.add(
            Post(id=1, title="Acme published", status="published", team_id=1, user_id=1)
        )
        db.add(Post(id=2, title="Acme draft", status="draft", team_id=1, user_id=1))
        db.add(
            Post(
                id=3, title="Globex published", status="published", team_id=2, user_id=2
            )
        )
        db.commit()


seed()


# --- Authorization: the app's own rules, expressed as scopes -------------------------

scopes = ScopeRegistry()
scopes.allow_all(User)
scopes.allow_all(TeamMember)


@scopes.register(Post)
def post_scope(ctx):  # type: ignore[no-untyped-def]
    """Only posts belonging to a team the principal is a member of.

    The membership lookup hits the database, which is the realistic case - access is
    not an attribute of the row. It runs once per request, not once per row.
    """
    team_ids = ctx.cache.get_or_set(
        "team_ids",
        lambda: list(
            ctx.db.exec(
                select(TeamMember.team_id).where(TeamMember.user_id == ctx.principal)
            ).all()
        ),
    )
    return Post.team_id.in_(team_ids)


# --- The endpoint --------------------------------------------------------------------

app = FastAPI(title="QueryMate example")
install_exception_handler(app)

# Declared per model, so it holds wherever the model is reached - including through
# posts.user. Declaring it only on the endpoint would leave that back door open.
resources = ResourceRegistry()
resources.register(User, Exposed(fields=["id", "name", "email"]))
resources.register(Post, Exposed(fields=["id", "title", "status"]))

UsersQuery = Querymate.for_model(User, resources=resources)


@app.get("/users")
def list_users(
    q: Querymate = Depends(UsersQuery),
    db: Session = Depends(get_db),
    as_user: int = Query(1, description="Pretend to be this user id."),
) -> object:
    return q.run(db, scopes=scopes.bind(principal=as_user, db=db))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
