import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

from ..configs.configs import get_settings

settings = get_settings()

API_KEY_HEADER_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=True)
VALID_API_KEY = settings.API_KEY


async def get_api_key(api_key: str = Security(api_key_header)) -> str:
    if not secrets.compare_digest(api_key, VALID_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid key",
            headers={"WWW-Authenticate": API_KEY_HEADER_NAME},
        )
    return api_key


APIKeyDep = Annotated[str, Depends[get_api_key]]
