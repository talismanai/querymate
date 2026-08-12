Models
======

QueryMate works with **SQLModel table classes and plain SQLAlchemy declarative
models**, and it does not need to be told which is which. There is no setting: the
class already says what it is, and asking an application to repeat that would only be
wrong the day it uses both.

.. code-block:: python

    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

    class Base(DeclarativeBase):
        pass

    class Author(Base):
        __tablename__ = "author"
        id: Mapped[int] = mapped_column(primary_key=True)
        name: Mapped[str]
        email: Mapped[str | None]
        books: Mapped[list["Book"]] = relationship(back_populates="author")

    Querymate(select=["id", "name", {"books": ["title"]}]).run(db, Author)

Everything applies equally: relationships and eager loading, filters across
relationships, computed counts, offset and cursor pagination, grouping, aggregation,
authorization scopes and field grants, the generated schema, and the descriptor.

Sessions
--------

Both session types work too. ``Session.exec`` is SQLModel's addition; a plain
``sqlalchemy.orm.Session`` has only ``execute``, and QueryMate uses whichever the
session provides — returning the same shape from both. The async path takes
``sqlalchemy.ext.asyncio.AsyncSession`` or SQLModel's.

Where the information comes from
--------------------------------

Both kinds of model are mapped, and the SQLAlchemy mapper answers every question
QueryMate asks of them:

.. list-table::
   :header-rows: 1

   * - Question
     - Answered by
   * - which fields exist
     - the mapper's column attributes (relationships excluded — they are not columns)
   * - what type a field has
     - the column's SQL type, falling back to the Pydantic annotation where there is
       one
   * - whether a field is nullable
     - the column, which is what the database actually enforces

The Pydantic fallback is not decoration: SQLModel maps ``str`` to its own
``AutoString``, whose ``python_type`` raises, so without it no SQLModel string field
would be recognised. Plain SQLAlchemy models never need it.

What is refused
---------------

A class that is not a mapped ORM model — a bare Pydantic model, say — has no columns
to query, and is refused with a ``TypeError`` saying so, rather than failing later on
a missing attribute.
