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


def chat_stream(messages: list[dict]):
    """流式聊天，yield 每个 token。"""
    client = _get_client()
    stream = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=messages,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def chat(messages: list[dict]) -> str:
    """非流式聊天，返回完整回答。"""
    client = _get_client()
    resp = client.chat.completions.create(model=settings.LLM_MODEL, messages=messages)
    return resp.choices[0].message.content
