import re


_CHINESE_ONLY_RE = re.compile(r"^[\u4e00-\u9fff]+$")
_KEY_CHARS_RE = re.compile(r"[^a-z0-9\u4e00-\u9fff]+")
_LATIN_WORDS_RE = re.compile(r"[A-Za-z]+")


def normalize_entity_key(text: str) -> str:
    value = text.strip().lower()
    if _CHINESE_ONLY_RE.fullmatch(value):
        return value
    return _KEY_CHARS_RE.sub("", value)


def alias_keys_for_surface(surface: str, entity_type: str = "") -> list[str]:
    aliases: list[str] = []

    def add_alias(key: str) -> None:
        if key and key not in aliases:
            aliases.append(key)

    add_alias(normalize_entity_key(surface))

    words = _LATIN_WORDS_RE.findall(surface.strip())
    if entity_type == "person" and len(words) == 2:
        first, second = (word.lower() for word in words)
        add_alias(first + second)
        add_alias(second + first)

    return aliases
