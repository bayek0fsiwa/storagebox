from typing import Annotated, AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from ..utils.loger import LoggerSetup
from .configs import get_settings

logger_setup = LoggerSetup(logger_name=__name__)
logger = logger_setup.logger

settings = get_settings()

db_value = settings.DATABASE_URI
if db_value.startswith("sqlite"):
    sqlite_url = db_value
else:
    sqlite_url = f"sqlite+aiosqlite:///{db_value}"

engine = create_async_engine(sqlite_url, echo=False, future=True)

async_session_maker = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def create_db_and_tables() -> None:
    try:
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        logger.info("Database tables created successfully.")
    except Exception:
        logger.exception("Error creating tables.")
        raise


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session


# SessionDep = get_session
SessionDep = Annotated[AsyncSession, Depends(get_session)]
