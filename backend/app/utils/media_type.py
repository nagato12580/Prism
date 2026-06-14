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

MIME_TO_MEDIA_TYPE = {
    "application/msword": "document",
    "application/pdf": "document",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "document",
    "text/markdown": "document",
    "text/plain": "document",
    "image/gif": "image",
    "image/jpeg": "image",
    "image/png": "image",
    "image/webp": "image",
    "audio/aac": "audio",
    "audio/flac": "audio",
    "audio/mp4": "audio",
    "audio/mpeg": "audio",
    "audio/ogg": "audio",
    "audio/wav": "audio",
    "audio/x-wav": "audio",
    "video/mp4": "video",
    "video/quicktime": "video",
    "video/webm": "video",
    "video/x-matroska": "video",
    "video/x-msvideo": "video",
}


def infer_media_type(filename: str, mime_type: str | None = None) -> str:
    ext = Path(filename or "").suffix.lower()
    if ext in EXTENSION_TO_MEDIA_TYPE:
        return EXTENSION_TO_MEDIA_TYPE[ext]

    mime = (mime_type or "").lower()
    if mime in MIME_TO_MEDIA_TYPE:
        return MIME_TO_MEDIA_TYPE[mime]

    raise ValueError(f"Unsupported file type: {ext or mime or 'unknown'}")


def supported_accept_extensions() -> str:
    return ",".join(sorted(EXTENSION_TO_MEDIA_TYPE))
