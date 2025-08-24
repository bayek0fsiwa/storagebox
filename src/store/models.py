from datetime import datetime
from typing import List, Optional

from sqlmodel import JSON, TIMESTAMP, Column, Field, SQLModel, text


class Storagebox(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True, index=True)
    otp: str = Field(
        nullable=False, unique=True, min_length=6, max_length=6, index=True
    )
    file_details: dict = Field(default_factory=dict, sa_column=Column(JSON))
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


class OtpRequestResponse(SQLModel):
    message: str
    otp: str


class OtpRequest(SQLModel):
    otp: str


class FileMetadata(SQLModel):
    original_filename: str
    file_type: str
    download_url: str
    file_size: Optional[int | None] = None


class AccessResponse(SQLModel):
    otp: str
    files: List[FileMetadata]
