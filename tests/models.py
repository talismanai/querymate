from datetime import date, datetime

from sqlmodel import Field, Relationship, SQLModel


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
