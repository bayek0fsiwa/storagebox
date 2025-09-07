from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr
from sqlmodel import TIMESTAMP, Column, Field, SQLModel, text


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    kc_id: Optional[str] = Field(default=None, index=True)
    username: str = Field(index=True)
    email: Optional[str] = Field(default=None, index=True)
    full_name: Optional[str] = None
    is_active: bool = Field(default=True)
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
        ),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=text("CURRENT_TIMESTAMP"),
            server_onupdate=text("CURRENT_TIMESTAMP"),
        ),
    )


class SignupIn(BaseModel):
    username: str
    email: EmailStr
    password: str
    full_name: str | None = None


class SigninIn(BaseModel):
    username: str
    password: str
