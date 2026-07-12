# prism/engine/app/llm/client.py
"""OpenAI 兼容 LLM 客户端，支持流式输出。"""
from openai import OpenAI
from ..config import settings

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(base_url=settings.LLM_API_BASE, api_key=settings.LLM_API_KEY)
    return _client


def _get_override_client(api_base: str, api_key: str):
    return OpenAI(base_url=api_base, api_key=api_key)


def chat_stream(messages: list[dict]):
    """流式聊天，yield 每个 token。"""
    client = _get_client()
    stream = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        stream=True,
    )
    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def chat(
    messages: list[dict],
    *,
    model: str | None = None,
    api_base: str | None = None,
    api_key: str | None = None,
) -> str:
    """非流式聊天，返回完整回答。"""
    selected_model = model or settings.LLM_MODEL
    selected_api_base = api_base or settings.LLM_API_BASE
    selected_api_key = api_key or settings.LLM_API_KEY
    client = _get_override_client(selected_api_base, selected_api_key) if api_base or api_key else _get_client()
    resp = client.chat.completions.create(model=selected_model, messages=messages)
    return resp.choices[0].message.content
