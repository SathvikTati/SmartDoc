import hashlib
import re

from fastapi import UploadFile


async def calculate_sha256(file: UploadFile) -> str:
    hasher = hashlib.sha256()

    await file.seek(0)

    while chunk := await file.read(1024 * 1024):
        hasher.update(chunk)

    await file.seek(0)

    return hasher.hexdigest()


def calculate_content_sha256(text: str) -> str:
    normalized_text = re.sub(
        r"\s+",
        " ",
        text
    ).strip()

    return hashlib.sha256(
        normalized_text.encode("utf-8")
    ).hexdigest()