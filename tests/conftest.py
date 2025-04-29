# type: ignore
"""Configuration file for pytest that also disables type checking for all test files."""

# This file's presence with the type: ignore comment will make mypy ignore all files in
# the tests directory

import pytest
from fastapi import FastAPI
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool


@pytest.fixture
def app():
    app = FastAPI()
    return app


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def db(engine):
    with Session(engine) as session:
        yield session
