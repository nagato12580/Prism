# prism/backend/app/prompts/renderer.py
"""Jinja2 prompt template renderer for Prism backend.

Template convention:
    Two-section templates use Jinja2 named blocks:

        {% block system %}
        ...system prompt...
        {% endblock %}

        {% block user %}
        ...user message...
        {% endblock %}

    `render_messages` extracts the rendered `system` and `user` blocks
    independently. Templates without these blocks should be rendered with
    `render_prompt`, which returns the entire output as a single string.

Usage:
    from app.prompts.renderer import render_prompt, render_messages

    # Two-section template -> (system, user) messages:
    system, user = render_messages("asset_parse.jinja2", content=..., title=...)

    # Single-section template -> one string:
    text = render_prompt("some_template.jinja2", name=...)
"""
import json as _json
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup

_TEMPLATES_DIR = Path(__file__).parent / "templates"

_SYSTEM_BLOCK = "system"
_USER_BLOCK = "user"


def _tojson_filter(value, ensure_ascii: bool = False, indent: int | None = None) -> Markup:
    """Custom tojson filter that defaults to ensure_ascii=False for Chinese text."""
    return Markup(_json.dumps(value, ensure_ascii=ensure_ascii, indent=indent))


@lru_cache(maxsize=1)
def _get_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["tojson"] = _tojson_filter
    return env


def render_prompt(template_name: str, **context) -> str:
    """Render a single-section template as one string."""
    return _get_env().get_template(template_name).render(**context).strip()


def render_messages(template_name: str, **context) -> tuple[str, str]:
    """Render a two-section template that defines `system` and `user` blocks.

    Returns:
        (system_prompt, user_message) tuple. If a block is missing, the
        corresponding string is empty.
    """
    template = _get_env().get_template(template_name)
    ctx = template.new_context(vars=context)

    def _render_block(name: str) -> str:
        block = template.blocks.get(name)
        if block is None:
            return ""
        return "".join(block(ctx)).strip()

    return _render_block(_SYSTEM_BLOCK), _render_block(_USER_BLOCK)


__all__ = ["render_prompt", "render_messages"]
