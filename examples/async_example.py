from typing import AsyncGenerator

from fastapi import Depends, FastAPI
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import sessionmaker

from querymate.core.querymate import Querymate


# Define your SQLModel
class User(SQLModel, table=True):  # type: ignore
    id: int = Field(primary_key=True)
    name: str
    email: str
    age: int


# Create FastAPI app
app = FastAPI()

# Create async database engine
DATABASE_URL = "sqlite+aiosqlite:///example.db"
engine = create_async_engine(
    DATABASE_URL,
    echo=True,
    future=True
)

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


# Example route using QueryMate with async database
@app.get("/users")
async def get_users(
    query: Querymate = Depends(Querymate.fastapi_dependency),
    db: AsyncSession = Depends(get_db),
):
    """
    Get users with filtering, sorting, pagination and field selection.
    
    Query parameters:
    - q: JSON string containing query configuration with the following structure:
        {
            "select": ["field1", "field2"],  # Fields to include in response
            "filter": {"field": {"operator": "value"}},  # Filter conditions
            "sort": ["field1", "-field2"],  # Sort fields (- for descending)
            "limit": 10,  # Maximum number of records (default: 10, max: 200)
            "offset": 0  # Number of records to skip (default: 0)
        }
    """
    return await query.run_async(db, User)


# Create database tables
@app.on_event("startup")
async def startup():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all) 