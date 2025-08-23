import sys
from typing import Annotated, AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from .configs import get_settings

envs = get_settings()

sqlite_file_name = envs.DATABASE_URI
sqlite_url = f"sqlite+aiosqlite:///{sqlite_file_name}"

connect_args = {"check_same_thread": False}


try:
    engine = create_async_engine(
        sqlite_url, connect_args=connect_args, echo=True, future=True
    )
except Exception as e:
    print(f"Error creating database engine: {e}", file=sys.stderr)
    raise


async def create_db_and_tables():
    try:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
    except Exception as e:
        print(f"Error creating tables: {e}", file=sys.stderr)
        raise


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(engine) as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
