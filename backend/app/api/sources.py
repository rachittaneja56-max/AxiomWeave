from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.auth import require_current_user
from app.models import User
from app.source_versions import normalize_source_text

router = APIRouter()

MAX_TEXT_FILE_BYTES = 80 * 1024
SUPPORTED_MEDIA_TYPES: dict[str, Literal["text/plain", "text/markdown"]] = {
    ".txt": "text/plain",
    ".md": "text/markdown",
}
ACCEPTED_UPLOAD_MEDIA_TYPES = {
    "application/octet-stream",
    "text/plain",
    "text/markdown",
    "text/x-markdown",
}


class ExtractedText(BaseModel):
    filename: str
    media_type: Literal["text/plain", "text/markdown"]
    character_count: int
    source_text: str


def source_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


@router.post("/sources/text-file", response_model=ExtractedText)
async def extract_text_file(
    file: Annotated[UploadFile, File()],
    _user: Annotated[User, Depends(require_current_user)],
) -> ExtractedText:
    filename = file.filename or ""
    extension = filename.rpartition(".")[2].lower()
    extension = f".{extension}" if extension else ""
    media_type = SUPPORTED_MEDIA_TYPES.get(extension)
    if media_type is None:
        await file.close()
        raise source_error(415, "unsupported_file", "Only .txt and .md files are supported.")

    content_type = (file.content_type or "application/octet-stream").split(";", 1)[0].lower()
    if content_type not in ACCEPTED_UPLOAD_MEDIA_TYPES:
        await file.close()
        raise source_error(415, "unsupported_media_type", "The uploaded file must be plain text.")

    try:
        content = await file.read(MAX_TEXT_FILE_BYTES + 1)
    finally:
        await file.close()

    if len(content) > MAX_TEXT_FILE_BYTES:
        raise source_error(413, "file_too_large", "The file exceeds the 80 KiB upload limit.")
    if not content:
        raise source_error(422, "empty_source", "The uploaded file is empty.")

    try:
        source_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise source_error(
            422, "invalid_encoding", "The file must contain valid UTF-8 text."
        ) from None

    try:
        source_text = normalize_source_text(source_text)
    except ValueError as error:
        if "non-whitespace" in str(error):
            raise source_error(422, "empty_source", "The uploaded file contains no text.") from None
        raise source_error(
            422,
            "source_too_long",
            "Extracted text exceeds the 20,000-character source limit.",
        ) from None

    return ExtractedText(
        filename=filename,
        media_type=media_type,
        character_count=len(source_text),
        source_text=source_text,
    )
