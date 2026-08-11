from datetime import UTC, date, datetime

from sqlmodel import Field, Relationship, SQLModel


class PostTagLink(SQLModel, table=True):
    """Association table backing the Post <-> Tag many-to-many relationship."""

    post_id: int | None = Field(default=None, foreign_key="post.id", primary_key=True)
    tag_id: int | None = Field(default=None, foreign_key="tag.id", primary_key=True)


class User(SQLModel, table=True):
    id: int = Field(primary_key=True)
    name: str
    email: str
    age: int
    is_active: bool
    status: str = Field(default="active")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    birth_date: date | None = None
    last_login: datetime | None = None
    posts: list["Post"] = Relationship(back_populates="user")
    profile: "Profile" = Relationship(
        back_populates="user", sa_relationship_kwargs={"uselist": False}
    )


class Post(SQLModel, table=True):
    id: int = Field(primary_key=True)
    title: str
    content: str
    status: str = Field(default="draft")
    user_id: int = Field(foreign_key="user.id")
    team_id: int | None = Field(default=None, foreign_key="team.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: datetime | None = None
    user: "User" = Relationship(back_populates="posts")
    comments: list["Comment"] = Relationship(back_populates="post")
    tags: list["Tag"] = Relationship(back_populates="posts", link_model=PostTagLink)


class Comment(SQLModel, table=True):
    """Third level of the hierarchy: User -> Post -> Comment.

    The bundled models used to stop at two levels, so nothing exercised deep nesting
    even though the documentation advertises it.
    """

    id: int = Field(primary_key=True)
    body: str
    approved: bool = Field(default=True)
    post_id: int = Field(foreign_key="post.id")
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    post: "Post" = Relationship(back_populates="comments")


class Tag(SQLModel, table=True):
    """Many-to-many with Post, through PostTagLink."""

    id: int = Field(primary_key=True)
    name: str
    posts: list["Post"] = Relationship(back_populates="tags", link_model=PostTagLink)


class Profile(SQLModel, table=True):
    """One-to-one with User."""

    id: int = Field(primary_key=True)
    bio: str
    user_id: int = Field(foreign_key="user.id", unique=True)
    user: "User" = Relationship(back_populates="profile")


# The models below exist so authorization scopes can be tested the way they are
# actually used: access is not a static attribute of a row, it has to be looked up
# (which teams is this user a member of? which company owns that team?).


class Company(SQLModel, table=True):
    id: int = Field(primary_key=True)
    name: str


class Team(SQLModel, table=True):
    id: int = Field(primary_key=True)
    name: str
    company_id: int = Field(foreign_key="company.id")


class TeamMember(SQLModel, table=True):
    id: int = Field(primary_key=True)
    team_id: int = Field(foreign_key="team.id")
    user_id: int = Field(foreign_key="user.id")
