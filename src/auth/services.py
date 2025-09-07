from typing import Optional

from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from .models import User


async def get_by_username(session: AsyncSession, username: str) -> Optional[User]:
    q = select(User).where(User.username == username)
    resp = await session.exec(q)
    return resp.scalar_one_or_none()


async def get_by_kc_id(session: AsyncSession, kc_id: str) -> Optional[User]:
    q = select(User).where(User.kc_id == kc_id)
    resp = await session.exec(q)
    return resp.scalar_one_or_none()


async def create_user(session: AsyncSession, **kwargs) -> User:
    user = User(**kwargs)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def delete_user_by_id(session: AsyncSession, id: str): ...
