from pathlib import Path
import shutil
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from port6.config import upload_config
from port6.services.model.models import Document
from port6.services.parsers.parser import (
    OcrLimitExceeded,
    ParsedDocument,
    parse,
)

from .filehash import (
    calculate_content_sha256,
    calculate_sha256,
)
from .magicbytevalidator import validate_magic_bytes


UPLOAD_DIR = Path(
    upload_config.get(
        "directory",
        "uploads",
    )
)

UPLOAD_DIR.mkdir(
    exist_ok=True,
)

MAX_SIZE = upload_config.get(
    "max_file_size_bytes",
    5 * 1024 * 1024,
)

MAX_FILES = upload_config.get(
    "max_files",
    5,
)

allowed_types = set(
    upload_config.get(
        "allowed_types",
        [],
    )
)


class FileSave(BaseModel):
    id: UUID
    filename: str
    type: str
    size_bytes: int
    path: Path
    content: ParsedDocument
    sha256: str


async def validate_files(
    files: list[UploadFile],
    db: Session,
):
    if len(files) > MAX_FILES:
        raise HTTPException(
            status_code=413,
            detail="More than 5 files are not allowed to upload",
        )

    result = []

    # Exact file hashes uploaded in this request
    uploaded_file_hashes = set()

    # Parsed-content hashes uploaded in this request
    uploaded_content_hashes = set()

    for file in files:

        # --------------------------------
        # SIZE VALIDATION
        # --------------------------------

        if file.size is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Could not determine size of "
                    f"{file.filename}"
                ),
            )

        if file.size > MAX_SIZE:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"{file.filename} is larger than "
                    f"{MAX_SIZE / (1024 * 1024):g} MB"
                ),
            )

        # --------------------------------
        # MIME TYPE VALIDATION
        # --------------------------------

        if file.content_type not in allowed_types:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{file.filename} has an unsupported "
                    f"file type: {file.content_type}"
                ),
            )

        # --------------------------------
        # MAGIC BYTE VALIDATION
        # --------------------------------

        magic_valid = await validate_magic_bytes(file)

        if not magic_valid:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{file.filename} does not match "
                    "its declared file type"
                ),
            )

        # --------------------------------
        # FILE SHA256
        # --------------------------------

        sha256 = await calculate_sha256(file)

        # Duplicate inside this request
        if sha256 in uploaded_file_hashes:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{file.filename} is an exact duplicate "
                    "within this upload request"
                ),
            )

        # Duplicate already stored
        existing_document = (
            db.query(Document)
            .filter(Document.sha256 == sha256)
            .first()
        )

        if existing_document:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{file.filename} is already uploaded "
                    f"as {existing_document.filename}"
                ),
            )

        uploaded_file_hashes.add(sha256)

        # --------------------------------
        # SAVE FILE
        # --------------------------------

        filename = Path(file.filename).name

        safe_filename = (
            f"{uuid4()}_{filename}"
        )

        file_path = (
            UPLOAD_DIR.absolute()
            / safe_filename
        )

        with file_path.open("wb") as buffer:
            shutil.copyfileobj(
                file.file,
                buffer,
            )

        # --------------------------------
        # PARSE
        # --------------------------------

        try:
            file_content = parse(file_path)

        except OcrLimitExceeded as exc:
            file_path.unlink(
                missing_ok=True,
            )

            # Not a parse failure — a deliberate refusal, with a limit the
            # uploader can act on. Saying "could not parse" here would
            # send someone looking for a corrupt file.
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{filename} was not accepted: {exc}"
                ),
            )

        except Exception as e:
            file_path.unlink(
                missing_ok=True,
            )

            raise HTTPException(
                status_code=400,
                detail=(
                    f"Could not parse "
                    f"{filename}: {str(e)}"
                ),
            )

        # --------------------------------
        # CONTENT SHA256
        # --------------------------------

        content_sha256 = calculate_content_sha256(
            file_content.text,
        )

        # Duplicate content inside request
        if content_sha256 in uploaded_content_hashes:
            file_path.unlink(
                missing_ok=True,
            )

            raise HTTPException(
                status_code=409,
                detail=(
                    f"{filename} contains the same "
                    "document content as another file "
                    "in this upload"
                ),
            )

        # Duplicate content already stored
        existing_content = (
            db.query(Document)
            .filter(
                Document.content_sha256
                == content_sha256
            )
            .first()
        )

        if existing_content:
            file_path.unlink(
                missing_ok=True,
            )

            raise HTTPException(
                status_code=409,
                detail=(
                    f"{filename} contains the same "
                    "document content as "
                    f"{existing_content.filename}"
                ),
            )

        uploaded_content_hashes.add(
            content_sha256
        )

        # --------------------------------
        # DATABASE
        # --------------------------------

        document = Document(
            filename=filename,
            file_type=file.content_type,
            size_bytes=file.size,
            sha256=sha256,
            content_sha256=content_sha256,
            storage_path=str(file_path),
            content=file_content.text,
            # Stored so nothing parses this file again. It matters most for
            # a scanned document, where re-parsing means re-running OCR.
            blocks=[
                block.model_dump()
                for block in file_content.blocks
            ],
            status="UPLOADED",
        )

        try:
            db.add(document)
            db.commit()
            db.refresh(document)

        except IntegrityError:
            db.rollback()

            file_path.unlink(
                missing_ok=True,
            )

            raise HTTPException(
                status_code=409,
                detail=(
                    f"{filename} is already stored"
                ),
            )

        except Exception as e:
            db.rollback()

            file_path.unlink(
                missing_ok=True,
            )

            raise HTTPException(
                status_code=500,
                detail=(
                    f"Could not save document: "
                    f"{str(e)}"
                ),
            )

        # --------------------------------
        # API RESPONSE
        # --------------------------------

        result.append(
            {
                "id": document.id,
                "filename": filename,
                "type": file.content_type,
                "size_bytes": file.size,
                "path": file_path,
                "content": file_content,
                "sha256": sha256,
            }
        )

    return result