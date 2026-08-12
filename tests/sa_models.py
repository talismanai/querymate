"""Plain SQLAlchemy declarative models, with no SQLModel or Pydantic anywhere.

Deliberately a separate hierarchy from ``tests/models.py``: the point is to prove the
library works on models it has never seen the Pydantic side of, so anything these
share with the SQLModel ones would weaken the test.
"""

from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """A project's own declarative base, unrelated to SQLModel's."""


class Author(Base):
    __tablename__ = "sa_author"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    # Nullable on purpose: nullability has to come from the column, since there is no
    # Pydantic FieldInfo to read it off.
    email: Mapped[str | None] = mapped_column(default=None)
    age: Mapped[int] = mapped_column(default=0)
    joined_at: Mapped[datetime | None] = mapped_column(default=None)

    books: Mapped[list["Book"]] = relationship(back_populates="author")


class Book(Base):
    __tablename__ = "sa_book"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    status: Mapped[str] = mapped_column(default="draft")
    author_id: Mapped[int] = mapped_column(ForeignKey("sa_author.id"))

    author: Mapped[Author] = relationship(back_populates="books")
