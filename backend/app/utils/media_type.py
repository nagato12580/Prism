from pathlib import Path

DOCUMENT_EXTENSIONS = {".pdf", ".doc", ".docx", ".txt", ".md", ".markdown"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

EXTENSION_TO_MEDIA_TYPE = {
    **{ext: "document" for ext in DOCUMENT_EXTENSIONS},
    **{ext: "image" for ext in IMAGE_EXTENSIONS},
    **{ext: "audio" for ext in AUDIO_EXTENSIONS},
    **{ext: "video" for ext in VIDEO_EXTENSIONS},
}


def infer_media_type(filename: str, mime_type: str | None = None) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext in EXTENSION_TO_MEDIA_TYPE:
        return EXTENSION_TO_MEDIA_TYPE[ext]

    mime = (mime_type or "").lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    if mime in {"application/pdf", "text/plain", "text/markdown"}:
        return "document"

    raise ValueError(f"Unsupported file type: {ext or mime or 'unknown'}")


def supported_accept_extensions() -> str:
    return ",".join(sorted(EXTENSION_TO_MEDIA_TYPE))
