# import mimetypes
# import pathlib
# import tempfile
# import uuid
# import zipfile
# from typing import Any, Dict, List, Optional

# import aiofiles
# import pyotp
# from fastapi import File, HTTPException, UploadFile, status
# from sqlalchemy.exc import IntegrityError
# from sqlmodel import select

# from src.configs.db import SessionDep
# from src.store.models import Storagebox

# from ..utils.loger import LoggerSetup

# BASE_DIR = pathlib.Path(__file__).parent.parent.parent
# UPLOAD_DIR = BASE_DIR / "uploads"
# UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
# _logger_setup: Optional[LoggerSetup] = None
# OTP_RETRY = 5


# def get_logger():
#     global _logger_setup
#     if _logger_setup is None:
#         _logger_setup = LoggerSetup(logger_name=__name__)
#     return _logger_setup.logger


# logger = get_logger()


# async def add_file(session: SessionDep, files: List[UploadFile] = File(...)):
#     if len(files) <= 0:
#         raise HTTPException(
#             status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
#             detail="Please provide file(s).",
#         )
#     file_details: List[Dict[str, Any]] = []
#     try:
#         for file in files:
#             unique_filename = f"{uuid.uuid4()}_{file.filename}"
#             secure_file_path = UPLOAD_DIR / unique_filename
#             async with aiofiles.open(secure_file_path, "wb") as f:
#                 while chunk := await file.read(8192):
#                     await f.write(chunk)
#             stat = await aiofiles.os.stat(str(secure_file_path))
#             size = stat.st_size
#             file_details.append(
#                 {
#                     "original_filename": file.filename,
#                     "stored_filename": unique_filename,
#                     "file_type": file.content_type,
#                     "file_size": size,
#                 }
#             )
#         created = None
#         for _ in range(OTP_RETRY):
#             otp_full = pyotp.random_base32()
#             otp6 = otp_full[:6]
#             box = Storagebox(otp=otp6, file_details=file_details)
#             session.add(box)
#             try:
#                 await session.commit()
#                 await session.refresh(box)
#                 created = box
#                 break
#             except IntegrityError:
#                 await session.rollback()
#                 logger.warning("OTP collision, retrying to generate unique OTP.")
#         if created is None:
#             for fd in file_details:
#                 try:
#                     p = UPLOAD_DIR / fd["stored_filename"]
#                     if p.exists():
#                         await aiofiles.os.remove(str(p))
#                 except Exception:
#                     logger.exception("Failed to remove orphaned file during cleanup.")

#             logger.error("Failed to generate unique OTP after retries.")
#             raise HTTPException(
#                 status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#                 detail="Could not generate unique OTP, try again later.",
#             )

#         logger.info("File(s) stored successfully.", extra={"otp": created.otp})
#         return {
#             "message": f"File(s) stored successfully {[f['original_filename'] for f in file_details]}",
#             "otp": created.otp,
#         }
#     except HTTPException:
#         raise
#     except Exception:
#         logger.exception("Error occured during file upload.")
#         for fd in file_details:
#             try:
#                 p = UPLOAD_DIR / fd["stored_filename"]
#                 if p.exists():
#                     await aiofiles.os.remove(str(p))
#             except Exception:
#                 logger.exception(
#                     "Failed to remove orphaned file during cleanup after error."
#                 )
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="Internal server error.",
#         )


# async def get_files(file_path: str):
#     async with aiofiles.open(file_path, "rb") as f:
#         while chunk := await f.read(8192):
#             yield chunk


# async def get_store_record_by_otp(session: SessionDep, otp: str) -> Storagebox:
#     if not otp:
#         raise HTTPException(
#             status_code=status.HTTP_400_BAD_REQUEST,
#             detail="Please provide correct otp.",
#         )
#     statement = select(Storagebox).where(Storagebox.otp == otp)
#     result = await session.exec(statement)
#     file_record = result.first()
#     if not file_record:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="Record not found for this OTP",
#         )
#     return file_record


# async def get_file_info_for_otp(session: SessionDep, otp: str) -> List[Dict[str, Any]]:
#     file_record = await get_store_record_by_otp(session, otp)
#     if (
#         not file_record.file_details
#         or not isinstance(file_record.file_details, list)
#         or not file_record.file_details
#     ):
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail="File details are missing or corrupted.",
#         )
#     files_info: List[Dict[str, Any]] = []
#     for file_detail in file_record.file_details:
#         original_filename = file_detail.get("original_filename", "downloaded_file")
#         stored_filename = file_detail.get("stored_filename")
#         file_type = file_detail.get("file_type")

#         if not stored_filename:
#             continue
#         file_path_on_disk = UPLOAD_DIR / stored_filename
#         if not file_path_on_disk.exists():
#             logger.warning(
#                 "Stored file missing on disk",
#                 extra={"stored_filename": stored_filename},
#             )
#             continue
#         if not file_type or file_type == "application/octet-stream":
#             guessed_type, _ = mimetypes.guess_type(original_filename)
#             file_type = guessed_type if guessed_type else "application/octet-stream"
#         files_info.append(
#             {
#                 "original_filename": original_filename,
#                 "stored_filename": stored_filename,
#                 "file_type": file_type,
#                 "file_size": file_detail.get("file_size"),
#                 "file_path": str(file_path_on_disk),
#             }
#         )
#     if not files_info:
#         raise HTTPException(
#             status_code=status.HTTP_404_NOT_FOUND,
#             detail="No valid files found for this OTP.",
#         )
#     return files_info


# async def generate_file_zip(files_data: List[Dict[str, Any]]):
#     with tempfile.NamedTemporaryFile(
#         prefix="files_", suffix=".zip", delete=False
#     ) as tmp:
#         tmp_path = pathlib.Path(tmp.name)
#     try:
#         with zipfile.ZipFile(
#             str(tmp_path), "w", zipfile.ZIP_DEFLATED, allowZip64=True
#         ) as zipf:
#             for file_info in files_data:
#                 file_path = file_info["file_path"]
#                 original_filename = file_info.get(
#                     "original_filename", pathlib.Path(file_path).name
#                 )
#                 arcname = pathlib.Path(original_filename).name
#                 if pathlib.Path(file_path).exists():
#                     zipf.write(file_path, arcname=arcname)
#                 else:
#                     logger.warning(
#                         "Skipping missing file when creating zip",
#                         extra={"file_path": file_path},
#                     )
#         async with aiofiles.open(str(tmp_path), "rb") as zf:
#             while chunk := await zf.read(8192):
#                 yield chunk
#     finally:
#         try:
#             if tmp_path.exists():
#                 await aiofiles.os.remove(str(tmp_path))
#         except Exception:
#             logger.exception("Failed to remove temporary zip file.")

import mimetypes
import pathlib
import tempfile
import uuid
import zipfile
from typing import Any, Dict, List, Optional

import aiofiles
import pyotp
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
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB per file


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
                while chunk := await file.read(8192):
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
            otp_full = pyotp.random_base32()
            otp6 = otp_full[:6]
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
                    if p.exists():
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
                if p.exists():
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
                if p.exists():
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
        while chunk := await f.read(8192):
            yield chunk


async def get_store_record_by_otp(session: SessionDep, otp: str) -> Storagebox:
    if not otp or not isinstance(otp, str) or len(otp.strip()) != 6:
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


async def get_file_info_for_otp(session: SessionDep, otp: str) -> List[Dict[str, Any]]:
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
        if not file_path_on_disk.exists():
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


async def generate_file_zip(files_data: List[Dict[str, Any]]):
    tmp_path: Optional[pathlib.Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="files_", suffix=".zip", delete=False
        ) as tmp:
            tmp_path = pathlib.Path(tmp.name)

        # create zip synchronously (zipfile is sync)
        with zipfile.ZipFile(
            str(tmp_path), "w", zipfile.ZIP_DEFLATED, allowZip64=True
        ) as zipf:
            for file_info in files_data:
                file_path = file_info.get("file_path")
                if not file_path:
                    logger.warning(
                        "Skipping file with no path when creating zip",
                        extra={"file_info": file_info},
                    )
                    continue
                original_filename = file_info.get(
                    "original_filename", pathlib.Path(file_path).name
                )
                arcname = pathlib.Path(_sanitize_filename(original_filename)).name
                if pathlib.Path(file_path).exists():
                    zipf.write(file_path, arcname=arcname)
                else:
                    logger.warning(
                        "Skipping missing file when creating zip",
                        extra={"file_path": file_path},
                    )

        # stream the zip file
        async with aiofiles.open(str(tmp_path), "rb") as zf:
            while chunk := await zf.read(8192):
                yield chunk

    finally:
        if tmp_path is not None:
            try:
                if tmp_path.exists():
                    await aiofiles.os.remove(str(tmp_path))
            except Exception:
                logger.exception("Failed to remove temporary zip file.")
