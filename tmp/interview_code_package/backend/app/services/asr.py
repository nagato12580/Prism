"""语音识别（ASR）：音频 → 文字。DashScope Paraformer 录音文件识别。

流程：读取本地音频 → multipart 上传到 DashScope 异步 ASR 接口
→ 轮询 task 状态 → 下载 transcription_url 获取转写文本。

统一入口 transcribe()，失败抛 ASRError（中文提示）。
"""
import asyncio
import os

import httpx

from ..config import settings

# DashScope 录音文件识别（异步）端点
_DASHSCOPE_SUBMIT = (
    "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"
)
_DASHSCOPE_TASK = "https://dashscope.aliyuncs.com/api/v1/tasks/{task_id}"
# 轮询：最多等约 60s（录音 <= 60s，转写一般几秒）
_POLL_INTERVAL = 1.5
_POLL_MAX = 40


class ASRError(Exception):
    """ASR 业务异常，message 为中文用户提示。"""


async def transcribe(
    provider: str,
    api_key: str,
    model: str,
    audio_path: str,
) -> str:
    """把音频文件转文字。

    Args:
        provider: ASR 服务商，支持 "dashscope" / "faster_whisper"
        api_key: DashScope API Key（faster_whisper 不需要）
        model: 模型名（DashScope 用 "paraformer-v2"，faster_whisper 忽略）
        audio_path: 本地音频文件路径

    Returns:
        转写文本

    Raises:
        ASRError: 转写失败（中文提示）
    """
    if provider not in ("dashscope", "faster_whisper"):
        raise ASRError(f"暂不支持的 ASR 服务商：{provider}")

    # 读音频文件，确定 MIME type
    ext = os.path.splitext(audio_path)[1].lower()
    mime_map = {
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".webm": "audio/webm",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
    }
    mime_type = mime_map.get(ext, "audio/webm")

    with open(audio_path, "rb") as fh:
        audio_bytes = fh.read()

    if provider == "faster_whisper":
        return await _transcribe_faster_whisper(audio_bytes, os.path.basename(audio_path), mime_type)

    return await _transcribe_dashscope(
        api_key, model, audio_bytes,
        os.path.basename(audio_path), mime_type,
    )


async def _transcribe_dashscope(
    api_key: str,
    model: str,
    audio_bytes: bytes,
    filename: str,
    mime_type: str,
) -> str:
    """DashScope Paraformer 异步录音文件识别（multipart 上传音频）。"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "X-DashScope-Async": "enable",
    }
    data = {
        "model": model,
        "parameters": '{"language_hints": ["zh", "en"]}',
    }
    files = {"file": (filename, audio_bytes, mime_type)}

    async with httpx.AsyncClient(timeout=30) as client:
        # 1) 提交任务（multipart 上传音频）
        resp = await client.post(
            _DASHSCOPE_SUBMIT,
            headers=headers,
            data=data,
            files=files,
        )
        if resp.status_code in (401, 403):
            raise ASRError("ASR 模型 API Key 无效或无权限")
        if resp.status_code >= 400:
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ASRError(f"ASR 服务请求失败（HTTP {e.response.status_code}），请稍后重试") from e
        task_id = (resp.json().get("output") or {}).get("task_id")
        if not task_id:
            raise ASRError("ASR 任务提交失败，请稍后重试")

        # 2) 轮询任务结果
        task_url = _DASHSCOPE_TASK.format(task_id=task_id)
        for _ in range(_POLL_MAX):
            await asyncio.sleep(_POLL_INTERVAL)
            poll = await client.get(
                task_url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if poll.status_code >= 400:
                try:
                    poll.raise_for_status()
                except httpx.HTTPStatusError as e:
                    raise ASRError(f"ASR 服务请求失败（HTTP {e.response.status_code}），请稍后重试") from e
            output = poll.json().get("output") or {}
            status = output.get("task_status")
            if status == "SUCCEEDED":
                return await _extract_dashscope_text(client, output)
            if status in ("FAILED", "CANCELED"):
                msg = output.get("message") or "识别失败"
                raise ASRError(f"语音识别失败：{msg}")
        raise ASRError("语音识别超时，请稍后重试")


async def _extract_dashscope_text(
    client: httpx.AsyncClient,
    output: dict,
) -> str:
    """从成功的任务结果里取转写文本。"""
    results = output.get("results") or []
    texts: list[str] = []
    for item in results:
        if (
            item.get("subtask_status")
            and item.get("subtask_status") != "SUCCEEDED"
        ):
            continue
        url = item.get("transcription_url")
        if not url:
            continue
        r = await client.get(url, timeout=20)
        if r.status_code >= 400:
            try:
                r.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ASRError(f"ASR 服务请求失败（HTTP {e.response.status_code}），请稍后重试") from e
        data = r.json()
        for t in data.get("transcripts") or []:
            txt = (t.get("text") or "").strip()
            if txt:
                texts.append(txt)
    text = "".join(texts).strip()
    # Return empty string instead of raising — caller decides how to handle no-speech
    return text


async def _transcribe_faster_whisper(
    audio_bytes: bytes,
    filename: str,
    mime_type: str,
) -> str:
    """通过 faster-whisper 容器服务转写音频。

    调用 docker-compose 中的 faster-whisper 服务 HTTP 接口。
    """
    url = f"{settings.WHISPER_SERVICE_URL}/transcribe"
    files = {"file": (filename, audio_bytes, mime_type)}

    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, files=files)
        if resp.status_code >= 400:
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ASRError(f"Whisper 服务请求失败（HTTP {e.response.status_code}），请稍后重试") from e
        data = resp.json()
        text = (data.get("text") or "").strip()
        return text  # empty string is OK — caller handles no-speech


__all__ = ["transcribe", "ASRError"]
