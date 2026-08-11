from fastapi import UploadFile


MAGIC_BYTES = {
    "application/pdf": [
        b"%PDF"
    ],
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [
        b"PK"
    ],
    "application/msword": [
        b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    ]
}


async def validate_magic_bytes(file: UploadFile) -> bool:

    if file.content_type not in MAGIC_BYTES:
        return True

    header = await file.read(8)

    await file.seek(0)

    for magic_byte in MAGIC_BYTES[file.content_type]:
        if header.startswith(magic_byte):
            return True

    return False