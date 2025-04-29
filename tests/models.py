from sqlmodel import Field, Relationship, SQLModel


class User(SQLModel, table=True):
    id: int = Field(primary_key=True)
    name: str
    email: str
    age: int
    posts: list["Post"] = Relationship(back_populates="user")


class Post(SQLModel, table=True):
    id: int = Field(primary_key=True)
    title: str
    content: str
    user_id: int = Field(foreign_key="user.id")
    user: "User" = Relationship(back_populates="posts")
