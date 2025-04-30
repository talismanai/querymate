from fastapi import Depends, FastAPI
from sqlmodel import Field, Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from querymate.core.querymate import Querymate


# Define your SQLModel
class User(SQLModel, table=True):  # type: ignore
    id: int = Field(primary_key=True)
    name: str
    email: str
    age: int


# Create FastAPI app
app = FastAPI()

# Create database engine
engine = create_engine(
    "sqlite:///example.db",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Create database tables
SQLModel.metadata.create_all(engine)


# Database dependency
def get_db():
    with Session(engine) as session:
        yield session


# Example route using QueryMate
@app.get("/users")
async def get_users(
    query: Querymate = Depends(Querymate.fastapi_dependency),
    db: Session = Depends(get_db),
):
    return query.run(db, User)


# Example query parameters:
# ?q={"filter": {"age": {"gt": 18}}, "sort": ["-name", "age"], "limit": 10, "offset": 0, "select": ["id", "name"]}

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
