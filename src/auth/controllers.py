from typing import Optional, Tuple

import httpx
from fastapi import APIRouter, HTTPException, Request, status

from src.configs.db import SessionDep

from ..configs.configs import get_settings
from .models import SigninIn, SignupIn
from .services import create_user, delete_user_by_id, get_by_username

settings = get_settings()
KC_URL = settings.KEYCLOAK_SERVER_URL
REALM = settings.KEYCLOAK_REALM
ADMIN_CLIENT_ID = settings.KC_ADMIN_CLIENT_ID
ADMIN_CLIENT_SECRET = settings.KC_ADMIN_CLIENT_SECRET
APP_CLIENT_ID = settings.KEYCLOAK_CLIENT_ID
APP_CLIENT_SECRET = settings.KEYCLOAK_CLIENT_SECRET

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_from_request(request: Optional[Request]) -> Tuple[httpx.AsyncClient, bool]:
    """
    Get the shared httpx client from app.state if available.
    Returns (client, is_fallback). If is_fallback is True the caller must close the client.
    """
    if request is None:
        return httpx.AsyncClient(timeout=10.0), True
    client = getattr(request.app.state, "httpx_client", None)
    if client is None:
        return httpx.AsyncClient(timeout=10.0), True
    return client, False


async def get_admin_token(client: httpx.AsyncClient) -> str:
    token_url = f"{KC_URL}/realms/{REALM}/protocol/openid-connect/token"
    try:
        r = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": ADMIN_CLIENT_ID,
                "client_secret": ADMIN_CLIENT_SECRET,
            },
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502, detail=f"Keycloak token error: {e.response.text}"
        ) from e
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502, detail=f"Keycloak request failed: {str(e)}"
        ) from e
    return r.json()["access_token"]


async def _get_role(
    role_name: str, admin_token: str, client: httpx.AsyncClient
) -> dict:
    try:
        r = await client.get(
            f"{KC_URL}/admin/realms/{REALM}/roles/{role_name}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch role '{role_name}': {e.response.text}",
        ) from e
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502, detail=f"Keycloak request failed: {str(e)}"
        ) from e
    return r.json()


async def assign_realm_role_to_user(
    user_id: str,
    role_name: str,
    client: httpx.AsyncClient,
    admin_token: Optional[str] = None,
):
    admin_token = admin_token or await get_admin_token(client)
    role = await _get_role(role_name, admin_token, client)
    try:
        r2 = await client.post(
            f"{KC_URL}/admin/realms/{REALM}/users/{user_id}/role-mappings/realm",
            json=[role],
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        r2.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to assign role '{role_name}' to user: {e.response.text}",
        ) from e
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502, detail=f"Keycloak request failed: {str(e)}"
        ) from e
    return True


async def remove_realm_role_from_user(
    user_id: str,
    role_name: str,
    client: httpx.AsyncClient,
    admin_token: Optional[str] = None,
):
    admin_token = admin_token or await get_admin_token(client)
    role = await _get_role(role_name, admin_token, client)
    try:
        r2 = await client.delete(
            f"{KC_URL}/admin/realms/{REALM}/users/{user_id}/role-mappings/realm",
            json=[role],
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        r2.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to remove role '{role_name}' from user: {e.response.text}",
        ) from e
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502, detail=f"Keycloak request failed: {str(e)}"
        ) from e
    return True


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupIn, session: SessionDep, request: Request):
    client, is_fallback = _client_from_request(request)

    if await get_by_username(session, payload.username):
        if is_fallback:
            await client.aclose()
        raise HTTPException(status_code=400, detail="username already exists")

    admin_token = await get_admin_token(client)
    create_url = f"{KC_URL}/admin/realms/{REALM}/users"
    body = {
        "username": payload.username,
        "email": payload.email,
        "enabled": True,
        "credentials": [
            {"type": "password", "value": payload.password, "temporary": False}
        ],
        "attributes": {"full_name": payload.full_name} if payload.full_name else {},
    }
    headers = {"Authorization": f"Bearer {admin_token}"}

    try:
        r = await client.post(create_url, json=body, headers=headers)
    except httpx.RequestError as e:
        if is_fallback:
            await client.aclose()
        raise HTTPException(
            status_code=502, detail=f"Keycloak request failed: {str(e)}"
        ) from e

    if r.status_code == 409:
        if is_fallback:
            await client.aclose()
        raise HTTPException(
            status_code=400, detail="username already exists in Keycloak"
        )

    if r.status_code not in (201, 204):
        if is_fallback:
            await client.aclose()
        raise HTTPException(status_code=502, detail=f"Keycloak error: {r.text}")

    location = r.headers.get("Location")
    if location:
        kc_user_id = location.rstrip("/").rsplit("/", 1)[-1]
    else:
        try:
            q = f"{create_url}?username={payload.username}"
            r2 = await client.get(q, headers=headers)
            r2.raise_for_status()
        except httpx.HTTPStatusError as e:
            if is_fallback:
                await client.aclose()
            raise HTTPException(
                status_code=502,
                detail=f"Failed to query Keycloak for created user: {e.response.text}",
            ) from e
        except httpx.RequestError as e:
            if is_fallback:
                await client.aclose()
            raise HTTPException(
                status_code=502, detail=f"Keycloak request failed: {str(e)}"
            ) from e

        users = r2.json()
        if not users:
            if is_fallback:
                await client.aclose()
            raise HTTPException(
                status_code=500, detail="Failed to obtain Keycloak user id"
            )
        kc_user_id = users[0]["id"]

    try:
        user = await create_user(
            session,
            kc_id=kc_user_id,
            username=payload.username,
            email=payload.email,
            full_name=payload.full_name,
        )
    except Exception as exc:
        try:
            await client.delete(f"{create_url}/{kc_user_id}", headers=headers)
        except Exception:
            pass
        if is_fallback:
            await client.aclose()
        raise HTTPException(status_code=500, detail="DB error") from exc

    try:
        await assign_realm_role_to_user(
            kc_user_id, "user", client=client, admin_token=admin_token
        )
    except HTTPException as role_exc:
        try:
            await client.delete(f"{create_url}/{kc_user_id}", headers=headers)
        except Exception:
            pass

        try:
            await delete_user_by_id(session, user.id)
        except Exception:
            pass

        if is_fallback:
            await client.aclose()
        raise role_exc

    if is_fallback:
        await client.aclose()

    return {"id": user.id, "kc_id": user.kc_id, "username": user.username}


@router.post("/signin")
async def signin(payload: SigninIn, request: Request):
    client, is_fallback = _client_from_request(request)

    token_url = f"{KC_URL}/realms/{REALM}/protocol/openid-connect/token"
    try:
        r = await client.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": APP_CLIENT_ID,
                "client_secret": APP_CLIENT_SECRET,
                "username": payload.username,
                "password": payload.password,
            },
        )
        if r.status_code in (400, 401):
            if is_fallback:
                await client.aclose()
            raise HTTPException(status_code=401, detail="Invalid credentials")
        r.raise_for_status()
    except httpx.HTTPStatusError as e:
        if is_fallback:
            await client.aclose()
        raise HTTPException(
            status_code=502, detail=f"Keycloak error: {e.response.text}"
        ) from e
    except httpx.RequestError as e:
        if is_fallback:
            await client.aclose()
        raise HTTPException(
            status_code=502, detail=f"Keycloak request failed: {str(e)}"
        ) from e

    if is_fallback:
        await client.aclose()
    return r.json()
