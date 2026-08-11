from typing import Annotated

from fastapi import FastAPI, File, UploadFile
from starlette import status

from port6.services.db.database import db_dependency
from port6.services.files.filevalidator import (
    FileSave,
    validate_files,
)


app = FastAPI()


@app.post(
    "/upload",
    response_model=list[FileSave],
    status_code=status.HTTP_200_OK,
)
async def upload_files(
    files: Annotated[list[UploadFile], File(...)],
    db: db_dependency,
):
    return await validate_files(files, db)