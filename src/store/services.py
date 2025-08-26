import asyncio
import mimetypes
import pathlib
import secrets
import string
import tempfile
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

import aiofiles
import aiofiles.os
from fastapi import File, HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from src.configs.db import SessionDep
from src.store.models import Storagebox

from ..utils.loger import LoggerSetup

BASE_DIR = pathlib.Path(__file__).parent.parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
_logger_setup: Optional[LoggerSetup] = None

# tune as needed
OTP_RETRY = 5
CHUNK_SIZE = 8192
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB per file
# threadpool used for sync-heavy operations (zip creation, path.exists checks) to avoid blocking loop
_threadpool = ThreadPoolExecutor(max_workers=2)


def get_logger():
    global _logger_setup
    if _logger_setup is None:
        _logger_setup = LoggerSetup(logger_name=__name__)
    return _logger_setup.logger


logger = get_logger()


def _sanitize_filename(name: str) -> str:
    # keep only final name, strip any path components and control characters
    cleaned = pathlib.Path(name).name
    # Remove problematic control chars
    cleaned = "".join(ch for ch in cleaned if 32 <= ord(ch) <= 0x10FFFF)
    return cleaned[:255]  # cap length


async def add_file(session: SessionDep, files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Please provide file(s).",
        )

    file_details: List[Dict[str, Any]] = []
    stored_paths: List[pathlib.Path] = []

    try:
        # store incoming files
        for file in files:
            original_filename = _sanitize_filename(file.filename or "uploaded_file")
            unique_filename = f"{uuid.uuid4().hex}_{original_filename}"
            secure_file_path = UPLOAD_DIR / unique_filename

            # stream write and enforce per-file size limit
            written = 0
            async with aiofiles.open(secure_file_path, "wb") as f:
                while chunk := await file.read(CHUNK_SIZE):
                    written += len(chunk)
                    if written > MAX_FILE_SIZE_BYTES:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"File {original_filename} exceeds allowed size.",
                        )
                    await f.write(chunk)

            stat = await aiofiles.os.stat(str(secure_file_path))
            size = stat.st_size

            file_details.append(
                {
                    "original_filename": original_filename,
                    "stored_filename": unique_filename,
                    "file_type": file.content_type,
                    "file_size": size,
                }
            )
            stored_paths.append(secure_file_path)

        # generate unique OTP and persist; handle unique constraint robustly
        created: Optional[Storagebox] = None
        for _ in range(OTP_RETRY):
            otp6 = "".join(secrets.choice(string.digits) for _ in range(6))
            box = Storagebox(otp=otp6, file_details=file_details)
            session.add(box)
            try:
                await session.commit()
                await session.refresh(box)
                created = box
                break
            except IntegrityError as ie:
                await session.rollback()
                # best-effort: assume unique constraint on otp caused it; log and retry
                logger.warning(
                    "IntegrityError while committing Storagebox; retrying OTP",
                    extra={"exc": str(ie)},
                )
                continue

        if created is None:
            # cleanup stored files
            for p in stored_paths:
                try:
                    if await aiofiles.os.path.exists(str(p)):
                        await aiofiles.os.remove(str(p))
                except Exception:
                    logger.exception("Failed to remove orphaned file during cleanup.")

            logger.error("Failed to generate unique OTP after retries.")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Could not generate unique OTP, try again later.",
            )

        logger.info("File(s) stored successfully.", extra={"otp": created.otp})
        return {
            "message": "Files stored successfully",
            "files": [f["original_filename"] for f in file_details],
            "otp": created.otp,
        }

    except HTTPException:
        # propagate known HTTP errors after ensuring any stored files are cleaned
        for p in stored_paths:
            try:
                if await aiofiles.os.path.exists(str(p)):
                    await aiofiles.os.remove(str(p))
            except Exception:
                logger.exception(
                    "Failed to remove orphaned file during cleanup after HTTPException."
                )
        raise
    except Exception as exc:
        logger.exception("Error occurred during file upload.")
        for p in stored_paths:
            try:
                if await aiofiles.os.path.exists(str(p)):
                    await aiofiles.os.remove(str(p))
            except Exception:
                logger.exception(
                    "Failed to remove orphaned file during cleanup after error."
                )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error.",
        ) from exc


async def get_files(file_path: str):
    async with aiofiles.open(file_path, "rb") as f:
        while chunk := await f.read(CHUNK_SIZE):
            yield chunk


async def get_store_record_by_otp(session: SessionDep, otp: str):
    if not otp or not isinstance(otp, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide correct otp.",
        )
    otp = otp.strip()
    if len(otp) != 6:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please provide correct otp.",
        )
    statement = select(Storagebox).where(Storagebox.otp == otp)
    result = await session.exec(statement)
    file_record = result.first()
    if not file_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Record not found for this OTP",
        )
    return file_record


async def get_file_info_for_otp(session: SessionDep, otp: str):
    file_record = await get_store_record_by_otp(session, otp)
    if not isinstance(file_record.file_details, list) or not file_record.file_details:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="File details are missing or corrupted.",
        )

    files_info: List[Dict[str, Any]] = []
    for file_detail in file_record.file_details:
        original_filename = file_detail.get("original_filename", "downloaded_file")
        stored_filename = file_detail.get("stored_filename")
        file_type = file_detail.get("file_type")

        if not stored_filename:
            logger.warning(
                "Missing stored_filename in file_detail",
                extra={"file_detail": file_detail},
            )
            continue
        file_path_on_disk = UPLOAD_DIR / stored_filename
        if not await aiofiles.os.path.exists(str(file_path_on_disk)):
            logger.warning(
                "Stored file missing on disk",
                extra={"stored_filename": stored_filename},
            )
            continue
        if not file_type or file_type == "application/octet-stream":
            guessed_type, _ = mimetypes.guess_type(original_filename)
            file_type = guessed_type if guessed_type else "application/octet-stream"
        files_info.append(
            {
                "original_filename": original_filename,
                "stored_filename": stored_filename,
                "file_type": file_type,
                "file_size": file_detail.get("file_size"),
                "file_path": str(file_path_on_disk),
            }
        )

    if not files_info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No valid files found for this OTP.",
        )
    return files_info


# helper used to create zip in a thread (sync code) to avoid blocking event loop
def _create_zip_file_on_disk(files_data: List[Dict[str, Any]], target_path: str):
    with zipfile.ZipFile(
        target_path, "w", zipfile.ZIP_DEFLATED, allowZip64=True
    ) as zipf:
        for file_info in files_data:
            file_path = file_info.get("file_path")
            if not file_path:
                continue
            original_filename = file_info.get(
                "original_filename", pathlib.Path(file_path).name
            )
            arcname = pathlib.Path(_sanitize_filename(original_filename)).name
            if pathlib.Path(file_path).exists():
                zipf.write(file_path, arcname=arcname)


async def generate_file_zip(files_data: List[Dict[str, Any]]):
    tmp_path: Optional[pathlib.Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="files_", suffix=".zip", delete=False
        ) as tmp:
            tmp_path = pathlib.Path(tmp.name)

        # run sync zip creation in threadpool
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            _threadpool, _create_zip_file_on_disk, files_data, str(tmp_path)
        )

        # stream the zip file
        async with aiofiles.open(str(tmp_path), "rb") as zf:
            while True:
                chunk = await zf.read(CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk

    finally:
        if tmp_path is not None:
            try:
                if await aiofiles.os.path.exists(str(tmp_path)):
                    await aiofiles.os.remove(str(tmp_path))
            except Exception:
                logger.exception("Failed to remove temporary zip file.")


async def get_store_record_by_stored_filename(
    session: SessionDep, stored_filename: str
):
    """
    Find the Storagebox record that contains a file_details entry with the given stored_filename.
    Raises 404 if not found.
    """
    if not stored_filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid stored_filename."
        )

    statement = select(Storagebox)
    result = await session.exec(statement)
    # iterate candidates and check their file_details for matching stored_filename
    for record in result.all():
        details = getattr(record, "file_details", []) or []
        for fd in details:
            if fd.get("stored_filename") == stored_filename:
                return record

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Record not found for stored filename.",
    )
