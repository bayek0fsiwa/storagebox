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

engine = create_async_engine(
    sqlite_url, connect_args=connect_args, echo=True, future=True
)


async def create_db_and_tables():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


# AsyncSessionLocal = async_sessionmaker(
#     bind=engine,
#     class_=AsyncSession,
#     expire_on_commit=False,
# )


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(engine) as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
