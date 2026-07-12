from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentTextQuality:
    ok: bool
    error_code: str = ""
    message: str = ""
    chars: int = 0
    page_count: int | None = None
    chars_per_page: float | None = None


def assess_document_text(
    text: str | None,
    *,
    page_count: int | None,
    max_chars: int,
    max_chars_per_page: int,
) -> DocumentTextQuality:
    chars = len(text or "")
    if chars > max_chars:
        return DocumentTextQuality(
            ok=False,
            error_code="text_too_large",
            message=(
                f"Parsed text is too large for vectorization: chars={chars}, "
                f"page_count={page_count or 'unknown'}, max_chars={max_chars}. "
                "Please re-upload the PDF or use a cleaner parsed version."
            ),
            chars=chars,
            page_count=page_count,
        )

    if page_count and page_count > 0:
        chars_per_page = chars / page_count
        if chars_per_page > max_chars_per_page:
            return DocumentTextQuality(
                ok=False,
                error_code="text_density_too_high",
                message=(
                    f"Parsed text density is abnormal: chars={chars}, page_count={page_count}, "
                    f"chars_per_page={chars_per_page:.1f}, max_chars_per_page={max_chars_per_page}. "
                    "Please re-upload the PDF or use a cleaner parsed version."
                ),
                chars=chars,
                page_count=page_count,
                chars_per_page=chars_per_page,
            )

    return DocumentTextQuality(ok=True, chars=chars, page_count=page_count)
