import mimetypes
import pathlib
from typing import List

from fastapi import (
    APIRouter,
    File,
    HTTPException,
    Path,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import ORJSONResponse, StreamingResponse

from src.configs.db import SessionDep
from src.store.models import (
    AccessResponse,
    FileMetadata,
    OtpRequest,
    OtpRequestResponse,
)
from src.store.services import (
    UPLOAD_DIR,
    add_file,
    generate_file_zip,
    get_file_info_for_otp,
    get_files,
)

router = APIRouter(prefix="/store", tags=["Storagebox routes"])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    # response_model=OtpRequestResponse,
    response_class=ORJSONResponse,
)
async def add_files_route(
    session: SessionDep,
    files: List[UploadFile] = File(...),
):
    data = await add_file(session=session, files=files)
    return OtpRequestResponse(message=data["message"], otp=data["otp"])


@router.post(
    "/access",
    response_model=AccessResponse,
    response_class=ORJSONResponse,
    status_code=status.HTTP_200_OK,
)
async def get_files_metadata_route(
    session: SessionDep,
    request: Request,
    otp_request: OtpRequest,
) -> AccessResponse:
    files_info = await get_file_info_for_otp(session=session, otp=otp_request.otp)
    response_files_metadata = []
    for file_info in files_info:
        # build a safe download URL using request.url_for (requires route name)
        download_url = str(
            request.url_for(
                "download_single_file", stored_filename=file_info["stored_filename"]
            )
        )
        response_files_metadata.append(
            FileMetadata(
                original_filename=file_info["original_filename"],
                file_type=file_info["file_type"],
                download_url=download_url,
                file_size=file_info["file_size"],
            )
        )
    return AccessResponse(otp=otp_request.otp, files=response_files_metadata)


@router.get(
    "/download/{stored_filename}",
    name="download_single_file",
    status_code=status.HTTP_200_OK,
)
async def download_single_file_route(
    session: SessionDep,
    request: Request,
    stored_filename: str = Path(...),
) -> StreamingResponse:
    # prevent path traversal: only allow basename
    if pathlib.Path(stored_filename).name != stored_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid filename."
        )

    file_path = UPLOAD_DIR / stored_filename
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="File not found on server."
        )

    etag = f'"{stored_filename}"'
    if request.headers.get("if-none-match") == etag:
        return Response(
            status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag}
        )

    content_type, _ = mimetypes.guess_type(file_path)
    if content_type is None:
        content_type = "application/octet-stream"

    # Use original filename if present in DB to present sensible filename to client
    # We can optionally look it up; quick attempt:
    try:
        files_info = await get_file_info_for_otp(
            session=session, otp=stored_filename[:6]
        )
        # try to find matching stored_filename entry
        original_name = None
        for fi in files_info:
            if fi["stored_filename"] == stored_filename:
                original_name = fi["original_filename"]
                break
    except Exception:
        original_name = None

    download_name = original_name or stored_filename

    headers = {
        "ETag": etag,
        "Cache-Control": "public, max-age=86400, immutable",
        # using attachment and sanitized filename
        "Content-Disposition": f'attachment; filename="{pathlib.Path(download_name).name}"',
    }

    return StreamingResponse(
        content=get_files(str(file_path)),
        media_type=content_type,
        headers=headers,
    )


@router.post(
    "/access/zip",
    response_class=StreamingResponse,
    status_code=status.HTTP_200_OK,
)
async def download_all_files_as_zip_route(otp_request: OtpRequest, session: SessionDep):
    files_to_zip_info = await get_file_info_for_otp(
        session=session, otp=otp_request.otp
    )
    files_data_for_zip = [
        {
            "file_path": str(UPLOAD_DIR / f_info["stored_filename"]),
            "original_filename": f_info["original_filename"],
        }
        for f_info in files_to_zip_info
    ]
    zip_filename = f"files_{otp_request.otp}.zip"
    headers = {
        "Content-Disposition": f'attachment; filename="{zip_filename}"',
    }
    return StreamingResponse(
        content=generate_file_zip(files_data_for_zip),
        media_type="application/zip",
        headers=headers,
    )
