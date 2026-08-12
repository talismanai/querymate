"""Two model hierarchies of identical shape, one per ORM.

The parity suite runs the same scenarios against both, so the models have to agree on
everything a query can see: attribute names, types, nullability, relationship
directions and cardinalities. Only the declaration style and the table names differ.

Deliberately not shared with ``tests/models.py``: the point is that nothing about the
result depends on which ORM declared the model, and reusing one side's definitions
would leave that untested on the other.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Column, ForeignKey, Integer, MetaData, Table
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlmodel import Field, Relationship, SQLModel

# ---------------------------------------------------------------------------
# SQLModel
# ---------------------------------------------------------------------------


class SmItemTag(SQLModel, table=True):
    __tablename__ = "sm_item_tag"

    item_id: int | None = Field(
        default=None, foreign_key="sm_item.id", primary_key=True
    )
    tag_id: int | None = Field(default=None, foreign_key="sm_tag.id", primary_key=True)


class SmOwner(SQLModel, table=True):
    __tablename__ = "sm_owner"

    id: int = Field(primary_key=True)
    name: str
    email: str | None = None
    age: int
    active: bool = True
    status: str = "active"
    joined_at: datetime | None = None

    items: list["SmItem"] = Relationship(back_populates="owner")
    profile: "SmProfile" = Relationship(
        back_populates="owner", sa_relationship_kwargs={"uselist": False}
    )


class SmItem(SQLModel, table=True):
    __tablename__ = "sm_item"

    id: int = Field(primary_key=True)
    title: str
    status: str = "draft"
    rank: int = 0
    owner_id: int = Field(foreign_key="sm_owner.id")

    owner: "SmOwner" = Relationship(back_populates="items")
    notes: list["SmNote"] = Relationship(back_populates="item")
    tags: list["SmTag"] = Relationship(back_populates="items", link_model=SmItemTag)


class SmNote(SQLModel, table=True):
    """Third level: Owner -> Item -> Note."""

    __tablename__ = "sm_note"

    id: int = Field(primary_key=True)
    body: str
    item_id: int = Field(foreign_key="sm_item.id")

    item: "SmItem" = Relationship(back_populates="notes")


class SmTag(SQLModel, table=True):
    __tablename__ = "sm_tag"

    id: int = Field(primary_key=True)
    label: str

    items: list["SmItem"] = Relationship(back_populates="tags", link_model=SmItemTag)


class SmProfile(SQLModel, table=True):
    __tablename__ = "sm_profile"

    id: int = Field(primary_key=True)
    bio: str
    owner_id: int = Field(foreign_key="sm_owner.id", unique=True)

    owner: "SmOwner" = Relationship(back_populates="profile")


# ---------------------------------------------------------------------------
# SQLAlchemy
# ---------------------------------------------------------------------------


class Base(DeclarativeBase):
    """A project's own declarative base, unrelated to SQLModel's."""


sa_item_tag = Table(
    "sa_item_tag",
    Base.metadata,
    Column("item_id", Integer, ForeignKey("sa_item.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("sa_tag.id"), primary_key=True),
)


class SaOwner(Base):
    __tablename__ = "sa_owner"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str | None] = mapped_column(default=None)
    age: Mapped[int] = mapped_column(default=0)
    active: Mapped[bool] = mapped_column(default=True)
    status: Mapped[str] = mapped_column(default="active")
    joined_at: Mapped[datetime | None] = mapped_column(default=None)

    items: Mapped[list["SaItem"]] = relationship(back_populates="owner")
    profile: Mapped["SaProfile"] = relationship(back_populates="owner", uselist=False)


class SaItem(Base):
    __tablename__ = "sa_item"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    status: Mapped[str] = mapped_column(default="draft")
    rank: Mapped[int] = mapped_column(default=0)
    owner_id: Mapped[int] = mapped_column(ForeignKey("sa_owner.id"))

    owner: Mapped["SaOwner"] = relationship(back_populates="items")
    notes: Mapped[list["SaNote"]] = relationship(back_populates="item")
    tags: Mapped[list["SaTag"]] = relationship(
        secondary=sa_item_tag, back_populates="items"
    )


class SaNote(Base):
    __tablename__ = "sa_note"

    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str]
    item_id: Mapped[int] = mapped_column(ForeignKey("sa_item.id"))

    item: Mapped["SaItem"] = relationship(back_populates="notes")


class SaTag(Base):
    __tablename__ = "sa_tag"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str]

    items: Mapped[list["SaItem"]] = relationship(
        secondary=sa_item_tag, back_populates="tags"
    )


class SaProfile(Base):
    __tablename__ = "sa_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    bio: Mapped[str]
    owner_id: Mapped[int] = mapped_column(ForeignKey("sa_owner.id"), unique=True)

    owner: Mapped["SaOwner"] = relationship(back_populates="profile")


# ---------------------------------------------------------------------------
# The pair
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Pack:
    """One ORM's version of the hierarchy, addressed by role rather than by name."""

    orm: str
    Owner: Any
    Item: Any
    Note: Any
    Tag: Any
    Profile: Any
    metadata: MetaData
    link: Any

    def owner(self, **values: Any) -> Any:
        return self.Owner(**values)


SQLMODEL_PACK = Pack(
    orm="sqlmodel",
    Owner=SmOwner,
    Item=SmItem,
    Note=SmNote,
    Tag=SmTag,
    Profile=SmProfile,
    metadata=SQLModel.metadata,
    link=SmItemTag,
)

SQLALCHEMY_PACK = Pack(
    orm="sqlalchemy",
    Owner=SaOwner,
    Item=SaItem,
    Note=SaNote,
    Tag=SaTag,
    Profile=SaProfile,
    metadata=Base.metadata,
    link=sa_item_tag,
)

PACKS = [SQLMODEL_PACK, SQLALCHEMY_PACK]
