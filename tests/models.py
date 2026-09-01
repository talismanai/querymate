from datetime import date, datetime

from sqlmodel import Field, Relationship, SQLModel


class Team(SQLModel, table=True):
    id: int = Field(primary_key=True)
    name: str
    users: list["User"] = Relationship(back_populates="team")


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
    team_id: int | None = Field(default=None, foreign_key="team.id")
    team: Team | None = Relationship(back_populates="users")
    posts: list["Post"] = Relationship(back_populates="user")


class Post(SQLModel, table=True):
    id: int = Field(primary_key=True)
    title: str
    content: str
    status: str = Field(default="draft")
    user_id: int = Field(foreign_key="user.id")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    published_at: datetime | None = None
    user: "User" = Relationship(back_populates="posts")
