# Voice Transcription Inbox Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add voice recording and upload to the Asset Inbox — audio → DashScope ASR transcription → existing AI parse pipeline → inbox pending review.

**Architecture:** New `asr.py` service module handles DashScope Paraformer transcription via multipart file upload. New `POST /api/v1/assets/voice` endpoint accepts audio file, transcribes it, then feeds the text into the existing `_create_asset_item_from_raw()` pipeline. Frontend `VoiceRecordButton` component provides record/upload UI and embeds into InboxPage above the text fragment form.

**Tech Stack:** DashScope Paraformer ASR, MediaRecorder API, FastAPI UploadFile

---

### Task 1: Add ASR Configuration

**Files:**
- Modify: `backend/app/config.py`
- Modify: `.env`
- Modify: `.env.prod.example`

- [ ] **Step 1: Add ASR settings to `backend/app/config.py`**

Add these three lines after the existing `EMBEDDING_DIM` setting:

```python
ASR_PROVIDER: str = os.getenv("ASR_PROVIDER", "dashscope")
ASR_API_KEY: str = os.getenv("ASR_API_KEY", "")
ASR_MODEL: str = os.getenv("ASR_MODEL", "paraformer-v2")
```

- [ ] **Step 2: Add ASR config to `.env`**

Append after existing embedding config:

```bash
# ASR 语音识别
ASR_PROVIDER=dashscope
ASR_API_KEY=
ASR_MODEL=paraformer-v2
```

- [ ] **Step 3: Add ASR config to `.env.prod.example`**

Same three lines appended at the bottom.

- [ ] **Step 4: Verify settings load correctly**

Run: `python -c "from backend.app.config import settings; print(f'ASR: {settings.ASR_PROVIDER} / {settings.ASR_MODEL}')"`
Expected: `ASR: dashscope / paraformer-v2`

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py .env .env.prod.example
git commit -m "feat: add ASR configuration settings

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Create ASR Service Module

**Files:**
- Create: `backend/app/services/asr.py`
- Create: `backend/tests/test_asr.py`

Background: DashScope Paraformer supports direct multipart file upload for async transcription. Read local audio → upload as `file` field to DashScope → poll task status → download transcription text. No additional infrastructure (MinIO/OSS) required.

- [ ] **Step 1: Write failing tests in `backend/tests/test_asr.py`**

```python
"""Tests for ASR service module."""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestTranscribeDashScope:
    """Test DashScope Paraformer transcription flow."""

    @pytest.mark.asyncio
    async def test_transcribe_success(self, monkeypatch):
        """Happy path: upload audio file via multipart, get transcription."""
        from backend.app.services.asr import transcribe

        submit_response = MagicMock()
        submit_response.status_code = 200
        submit_response.json.return_value = {
            "output": {"task_id": "task-abc-123"}
        }

        poll_succeeded = MagicMock()
        poll_succeeded.status_code = 200
        poll_succeeded.json.return_value = {
            "output": {
                "task_status": "SUCCEEDED",
                "results": [{
                    "subtask_status": "SUCCEEDED",
                    "transcription_url": "http://dashscope.example.com/result.json",
                }],
            }
        }

        transcript_response = MagicMock()
        transcript_response.status_code = 200
        transcript_response.json.return_value = {
            "transcripts": [{"text": "这是语音转写的结果文本"}],
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = submit_response
        mock_client.get.side_effect = [poll_succeeded, transcript_response]

        monkeypatch.setattr(
            "backend.app.services.asr.httpx.AsyncClient",
            lambda **kwargs: mock_client,
        )

        # Create a temp file for the test
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tf:
            tf.write(b"fake audio data")
            tmp_path = tf.name

        try:
            result = await transcribe(
                provider="dashscope",
                api_key="sk-test-key",
                model="paraformer-v2",
                audio_path=tmp_path,
            )
            assert result == "这是语音转写的结果文本"
            mock_client.post.assert_called_once()
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_transcribe_no_speech(self, monkeypatch):
        """ASR returns empty text, raise ASRError."""
        from backend.app.services.asr import transcribe, ASRError

        submit_response = MagicMock()
        submit_response.status_code = 200
        submit_response.json.return_value = {"output": {"task_id": "task-empty"}}

        poll_succeeded = MagicMock()
        poll_succeeded.status_code = 200
        poll_succeeded.json.return_value = {
            "output": {
                "task_status": "SUCCEEDED",
                "results": [{
                    "subtask_status": "SUCCEEDED",
                    "transcription_url": "http://dashscope.example.com/result.json",
                }],
            }
        }

        empty_transcript = MagicMock()
        empty_transcript.status_code = 200
        empty_transcript.json.return_value = {"transcripts": [{"text": ""}]}

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = submit_response
        mock_client.get.side_effect = [poll_succeeded, empty_transcript]

        monkeypatch.setattr(
            "backend.app.services.asr.httpx.AsyncClient",
            lambda **kwargs: mock_client,
        )

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tf:
            tf.write(b"silence")
            tmp_path = tf.name

        try:
            with pytest.raises(ASRError) as exc_info:
                await transcribe(
                    provider="dashscope",
                    api_key="sk-test-key",
                    model="paraformer-v2",
                    audio_path=tmp_path,
                )
            assert "未识别到语音内容" in str(exc_info.value)
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_transcribe_task_failed(self, monkeypatch):
        """DashScope task status FAILED, raise ASRError."""
        from backend.app.services.asr import transcribe, ASRError

        submit_response = MagicMock()
        submit_response.status_code = 200
        submit_response.json.return_value = {"output": {"task_id": "task-fail"}}

        poll_failed = MagicMock()
        poll_failed.status_code = 200
        poll_failed.json.return_value = {
            "output": {
                "task_status": "FAILED",
                "message": "Audio format not supported",
            }
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = submit_response
        mock_client.get.return_value = poll_failed

        monkeypatch.setattr(
            "backend.app.services.asr.httpx.AsyncClient",
            lambda **kwargs: mock_client,
        )

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tf:
            tf.write(b"bad audio")
            tmp_path = tf.name

        try:
            with pytest.raises(ASRError) as exc_info:
                await transcribe(
                    provider="dashscope",
                    api_key="sk-test-key",
                    model="paraformer-v2",
                    audio_path=tmp_path,
                )
            assert "语音识别失败" in str(exc_info.value)
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_transcribe_unsupported_provider(self):
        """Unknown provider, raise ASRError."""
        from backend.app.services.asr import transcribe, ASRError

        with pytest.raises(ASRError) as exc_info:
            await transcribe(
                provider="unknown-provider",
                api_key="sk-test",
                model="v1",
                audio_path="/tmp/test.webm",
            )
        assert "暂不支持的 ASR 服务商" in str(exc_info.value)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_asr.py -v`
Expected: FAIL — no module `backend.app.services.asr`

- [ ] **Step 3: Create `backend/app/services/asr.py`**

```python
"""语音识别（ASR）：音频 → 文字。DashScope Paraformer 录音文件识别。

流程：读取本地音频 → multipart 上传到 DashScope 异步 ASR 接口
→ 轮询 task 状态 → 下载 transcription_url 获取转写文本。

统一入口 transcribe()，失败抛 ASRError（中文提示）。
"""
import asyncio
import os

import httpx

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
        provider: ASR 服务商，当前仅支持 "dashscope"
        api_key: DashScope API Key
        model: 模型名，默认 "paraformer-v2"
        audio_path: 本地音频文件路径

    Returns:
        转写文本

    Raises:
        ASRError: 转写失败（中文提示）
    """
    if provider not in ("dashscope",):
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
        resp.raise_for_status()
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
            poll.raise_for_status()
            output = poll.json().get("output") or {}
            status = output.get("task_status")
            if status == "SUCCEEDED":
                return await _extract_dashscope_text(client, output)
            if status in ("FAILED", "CANCELED"):
                msg = output.get("message") or "识别失败"
                raise ASRError(f"语音识别失败：{msg}")
        raise ASRError("语音识别超时，请重试或缩短录音")


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
        r.raise_for_status()
        data = r.json()
        for t in data.get("transcripts") or []:
            txt = (t.get("text") or "").strip()
            if txt:
                texts.append(txt)
    text = "".join(texts).strip()
    if not text:
        raise ASRError("未识别到语音内容，请说清楚后重试")
    return text


__all__ = ["transcribe", "ASRError"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_asr.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/asr.py backend/tests/test_asr.py
git commit -m "feat: add DashScope ASR service module

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Add POST /api/v1/assets/voice Endpoint

**Files:**
- Modify: `backend/app/api/assets.py`
- Create: `backend/tests/test_asset_voice.py`

- [ ] **Step 1: Write failing integration test in `backend/tests/test_asset_voice.py`**

```python
"""Integration tests for POST /api/v1/assets/voice."""
import io


class TestVoiceToAsset:
    """Test voice-to-asset-item endpoint."""

    def test_voice_endpoint_rejects_empty_file(self, client):
        """Upload with no file, FastAPI returns 422."""
        response = client.post("/api/v1/assets/voice")
        assert response.status_code == 422

    def test_voice_endpoint_rejects_unsupported_format(self, client):
        """Upload .txt file, 400 unsupported_audio_format."""
        files = {
            "audio_file": ("test.txt", io.BytesIO(b"not audio"), "text/plain"),
        }
        response = client.post("/api/v1/assets/voice", files=files)
        assert response.status_code == 400
        detail = response.json().get("detail", {})
        assert detail.get("code") == "unsupported_audio_format"

    def test_voice_creates_asset_item(self, client, monkeypatch):
        """Happy path: upload audio, transcribe, create asset item."""
        # Mock ASR to return fixed text
        async def mock_transcribe(**kwargs):
            return "这是语音转写的内容"
        monkeypatch.setattr(
            "backend.app.services.asr.transcribe",
            mock_transcribe,
        )

        # Mock AI parsing
        monkeypatch.setattr(
            "backend.app.api.assets._ai_parse_asset",
            lambda **kwargs: {
                "title": "转写标题",
                "summary": "转写摘要",
                "asset_kind": "idea",
                "category": "product",
                "tags": ["test"],
                "source_type": "voice",
                "source_platform": "",
                "source_url": "",
                "media_type": "text",
                "extracts": [],
                "suggested_relations": [],
                "suggested_extensions": [],
                "confidence": {"overall": 0.8},
                "rationale": "test",
                "rewritten_content": "改写内容",
            },
        )

        files = {
            "audio_file": ("recording.webm", io.BytesIO(b"fake webm audio"), "audio/webm"),
        }
        response = client.post("/api/v1/assets/voice", files=files)
        assert response.status_code == 201
        data = response.json()
        assert data["raw_source_type"] == "voice"
        assert "raw_metadata" in data
        assert data["raw_metadata"].get("audio_path", "").endswith(".webm")
        assert data["status"] == "pending_review"

    def test_voice_endpoint_handles_asr_error(self, client, monkeypatch):
        """ASR fails, 500 with user-friendly message."""
        async def mock_transcribe(**kwargs):
            from backend.app.services.asr import ASRError
            raise ASRError("语音识别失败：测试错误")

        monkeypatch.setattr(
            "backend.app.services.asr.transcribe",
            mock_transcribe,
        )

        files = {
            "audio_file": ("recording.webm", io.BytesIO(b"fake audio"), "audio/webm"),
        }
        response = client.post("/api/v1/assets/voice", files=files)
        assert response.status_code == 500
        detail = response.json().get("detail", {})
        assert "语音识别失败" in str(detail)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_asset_voice.py::TestVoiceToAsset::test_voice_creates_asset_item -v`
Expected: FAIL — 405 or 404 (endpoint not found)

- [ ] **Step 3: Add the voice endpoint to `backend/app/api/assets.py`**

First, add the necessary imports at the top of the file. The existing import line has `APIRouter, Depends, HTTPException, Query`. Change it to:

```python
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
```

Then add `import os` and `import uuid` to the standard library imports section.

Then add the voice endpoint code after the existing `POST /assets/items` endpoint (after the `create_asset_item` function ending around line 488):

```python
# ---------------------------------------------------------------------------
# Voice-to-asset-item
# ---------------------------------------------------------------------------

AUDIO_UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "voice"
AUDIO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
_ALLOWED_AUDIO_EXTENSIONS = {".mp3", ".wav", ".webm", ".m4a", ".aac"}
_MAX_AUDIO_SIZE_MB = 25
_MAX_AUDIO_SIZE_BYTES = _MAX_AUDIO_SIZE_MB * 1024 * 1024


def _validate_audio_format(filename: str, content_type: str | None) -> str:
    """Validate audio file extension and return lowercase extension.

    Raises HTTPException(400) on unsupported format.
    """
    ext = os.path.splitext(filename or "")[1].lower()
    # Fallback: try to infer extension from MIME type
    mime_to_ext = {
        "audio/webm": ".webm",
        "audio/mpeg": ".mp3",
        "audio/mp3": ".mp3",
        "audio/wav": ".wav",
        "audio/wave": ".wav",
        "audio/x-m4a": ".m4a",
        "audio/mp4": ".m4a",
        "audio/aac": ".aac",
    }
    if ext not in _ALLOWED_AUDIO_EXTENSIONS and content_type:
        ext = mime_to_ext.get(content_type, ext)
    if ext not in _ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unsupported_audio_format",
                "message": f"不支持的音频格式：{ext or '未知'}，支持 mp3/wav/webm/m4a/aac",
            },
        )
    return ext


@router.post("/voice", response_model=PersonalAssetItemOut, status_code=201)
async def voice_to_asset_item(
    audio_file: UploadFile = File(...),
    source_type: str = Form("recording"),
    db: Session = Depends(get_db),
):
    """语音转写并创建资产碎片。

    接收音频文件，通过 DashScope ASR 转写为文字，然后走
    _create_asset_item_from_raw() 进行 AI 解析并放入收件箱。
    """
    # 1) 验证文件大小（读入内存校验）
    audio_bytes = await audio_file.read()
    if len(audio_bytes) > _MAX_AUDIO_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "file_too_large",
                "message": f"音频文件不能超过 {_MAX_AUDIO_SIZE_MB}MB",
            },
        )

    # 2) 验证格式
    ext = _validate_audio_format(audio_file.filename or "", audio_file.content_type)

    # 3) 保存到本地
    audio_name = f"{uuid.uuid4().hex}{ext}"
    audio_path = AUDIO_UPLOAD_DIR / audio_name
    audio_path.write_bytes(audio_bytes)

    # 4) 调用 ASR 转写
    from ..services.asr import transcribe, ASRError

    try:
        text = await transcribe(
            provider=settings.ASR_PROVIDER,
            api_key=settings.ASR_API_KEY,
            model=settings.ASR_MODEL,
            audio_path=str(audio_path),
        )
    except ASRError as exc:
        raise HTTPException(
            status_code=500,
            detail={"code": "asr_failed", "message": str(exc)},
        ) from exc

    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_speech_detected",
                "message": "未检测到语音内容，请重新录制",
            },
        )

    # 5) 走现有资产创建管线
    return _create_asset_item_from_raw(
        db=db,
        raw_text=text.strip(),
        raw_source_type="voice",
        raw_source_platform=source_type,  # "recording" or "upload"
        raw_metadata={
            "audio_path": str(audio_path.relative_to(AUDIO_UPLOAD_DIR.parent)),
            "audio_filename": audio_file.filename,
            "audio_content_type": audio_file.content_type,
            "audio_size_bytes": len(audio_bytes),
        },
    )
```

Note: `Path` is already imported in assets.py. If not, add `from pathlib import Path`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_asset_voice.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/assets.py backend/tests/test_asset_voice.py
git commit -m "feat: add POST /api/v1/assets/voice endpoint

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Add Frontend API Function

**Files:**
- Modify: `frontend/src/app/api.ts`

- [ ] **Step 1: Add `createVoice` to `assetApi`**

In `frontend/src/app/api.ts`, find the `assetApi` object. Add the following function inside it:

```typescript
  /** Upload audio for voice transcription → creates an inbox asset item. */
  createVoice: (blob: Blob, filename: string, sourceType: string = 'recording'): Promise<AssetDraft> => {
    const form = new FormData()
    form.append('audio_file', blob, filename)
    form.append('source_type', sourceType)
    return uploadRequest<AssetDraft>('/assets/voice', form)
  },
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors related to api.ts

- [ ] **Step 3: Commit**

```bash
git add frontend/src/app/api.ts
git commit -m "feat: add assetApi.createVoice for voice-to-inbox

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Create VoiceRecordButton Component

**Files:**
- Create: `frontend/src/components/VoiceRecordButton.tsx`

- [ ] **Step 1: Create `frontend/src/components/VoiceRecordButton.tsx`**

```typescript
import { useEffect, useRef, useState, type DragEvent } from 'react'
import { Loader2, Mic, MicOff, Upload } from 'lucide-react'
import { assetApi, type AssetDraft } from '@/app/api'

const MAX_RECORD_SECONDS = 60

interface Props {
  onResult: (item: AssetDraft) => void
  onError: (message: string) => void
}

type Status = 'idle' | 'recording' | 'processing'

export default function VoiceRecordButton({ onResult, onError }: Props) {
  const [status, setStatus] = useState<Status>('idle')
  const [elapsed, setElapsed] = useState(0)
  const [isDragOver, setIsDragOver] = useState(false)

  const mediaRecorder = useRef<MediaRecorder | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<number | null>(null)

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current)
      streamRef.current?.getTracks().forEach((t) => t.stop())
      if (mediaRecorder.current?.state === 'recording') {
        mediaRecorder.current.stop()
      }
    }
  }, [])

  const cleanup = () => {
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    mediaRecorder.current = null
  }

  const startRecording = async () => {
    setElapsed(0)
    chunksRef.current = []

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      const recorder = new MediaRecorder(stream, {
        mimeType: MediaRecorder.isTypeSupported('audio/webm')
          ? 'audio/webm'
          : 'audio/mp4',
      })
      mediaRecorder.current = recorder

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }

      recorder.onstop = async () => {
        setStatus('processing')
        cleanup()

        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || 'audio/webm',
        })
        if (blob.size < 1000) {
          setStatus('idle')
          onError('录音太短，请重新录制。')
          return
        }

        const ext = recorder.mimeType?.includes('webm') ? 'webm' : 'm4a'
        try {
          const item = await assetApi.createVoice(
            blob,
            `recording.${ext}`,
            'recording',
          )
          setStatus('idle')
          onResult(item)
        } catch (err) {
          setStatus('idle')
          const msg =
            err instanceof Error ? err.message : '语音转写失败，请重试。'
          if (msg.includes('ASR') || msg.includes('模型') || msg.includes('Key')) {
            onError('ASR 服务未配置或不可用，请检查 .env 中的 ASR_API_KEY。')
          } else {
            onError(msg)
          }
        }
      }

      recorder.start()
      setStatus('recording')

      timerRef.current = window.setInterval(() => {
        setElapsed((prev) => {
          if (prev >= MAX_RECORD_SECONDS - 1) {
            stopRecording()
            return MAX_RECORD_SECONDS
          }
          return prev + 1
        })
      }, 1000)

      // Auto-stop at max duration
      setTimeout(() => {
        if (mediaRecorder.current?.state === 'recording') {
          stopRecording()
        }
      }, MAX_RECORD_SECONDS * 1000)
    } catch {
      onError('无法访问麦克风，请检查浏览器权限设置或使用文件上传。')
    }
  }

  const stopRecording = () => {
    if (mediaRecorder.current?.state === 'recording') {
      mediaRecorder.current.stop()
    }
  }

  const handleClick = () => {
    if (status === 'processing') return
    if (status === 'recording') {
      stopRecording()
    } else {
      startRecording()
    }
  }

  const handleFile = async (file: File) => {
    if (!file.type.startsWith('audio/') && !file.name.match(/\.(mp3|wav|webm|m4a|aac)$/i)) {
      onError('不支持的音频格式，请选择 mp3/wav/webm/m4a/aac 文件。')
      return
    }
    setStatus('processing')
    try {
      const item = await assetApi.createVoice(file, file.name, 'upload')
      setStatus('idle')
      onResult(item)
    } catch (err) {
      setStatus('idle')
      onError(err instanceof Error ? err.message : '文件上传转写失败。')
    }
  }

  const handleDrop = (e: DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  const handleDragOver = (e: DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }

  const handleDragLeave = () => setIsDragOver(false)

  const formatTime = (s: number) => {
    const min = Math.floor(s / 60)
    const sec = s % 60
    return `${min.toString().padStart(2, '0')}:${sec.toString().padStart(2, '0')}`
  }

  const progressPct = (elapsed / MAX_RECORD_SECONDS) * 100

  return (
    <div
      className={`rounded-lg border-2 p-4 transition ${
        isDragOver
          ? 'border-[var(--prism-blue)] bg-blue-50'
          : status === 'recording'
            ? 'border-red-300 bg-red-50'
            : 'border-dashed border-slate-200 bg-gradient-to-br from-blue-50 to-purple-50'
      }`}
      onDrop={handleDrop}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
    >
      <div className="flex items-center gap-4">
        {/* Record/Stop button */}
        <button
          type="button"
          disabled={status === 'processing'}
          onClick={handleClick}
          className={`flex h-11 w-11 items-center justify-center rounded-full border-2 transition ${
            status === 'recording'
              ? 'animate-pulse border-red-400 bg-red-100 text-red-600'
              : 'border-slate-200 bg-white text-[var(--prism-blue)] hover:border-blue-300 hover:shadow-sm'
          } disabled:opacity-50`}
        >
          {status === 'processing' ? (
            <Loader2 size={20} className="animate-spin" />
          ) : status === 'recording' ? (
            <MicOff size={20} />
          ) : (
            <Mic size={20} />
          )}
        </button>

        {/* Status text */}
        <div className="flex-1 min-w-0">
          {status === 'idle' && (
            <>
              <div className="text-[13px] font-semibold text-slate-900">语音录入</div>
              <div className="text-[11px] text-slate-500">
                点击录音或拖拽音频文件到此处
              </div>
            </>
          )}
          {status === 'recording' && (
            <>
              <div className="text-[13px] font-semibold text-red-700">正在录音...</div>
              <div className="flex items-center gap-2">
                <div className="h-1.5 flex-1 rounded-full bg-red-200">
                  <div
                    className="h-full rounded-full bg-red-500 transition-all duration-1000"
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
                <span className="text-[11px] font-mono tabular-nums text-red-600">
                  {formatTime(elapsed)}
                </span>
              </div>
            </>
          )}
          {status === 'processing' && (
            <>
              <div className="text-[13px] font-semibold text-[var(--prism-blue)]">
                智能处理中...
              </div>
              <div className="text-[11px] text-slate-500">
                语音转写 → AI 解析 → 放入收件箱
              </div>
            </>
          )}
        </div>

        {/* File upload button */}
        {status === 'idle' && (
          <label className="flex cursor-pointer items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-[10px] text-slate-500 transition hover:border-blue-200 hover:text-[var(--prism-blue)]">
            <Upload size={13} />
            <span>上传</span>
            <input
              type="file"
              accept="audio/*"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                if (file) handleFile(file)
                e.target.value = ''
              }}
            />
          </label>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors. If `Mic`/`MicOff` icons are missing from lucide-react, use `import { Mic, MicOff } from 'lucide-react'` or fall back to text labels.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/VoiceRecordButton.tsx
git commit -m "feat: add VoiceRecordButton component

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Embed VoiceRecordButton in InboxPage

**Files:**
- Modify: `frontend/src/pages/InboxPage.tsx`

- [ ] **Step 1: Embed VoiceRecordButton in InboxPage**

In `frontend/src/pages/InboxPage.tsx`:

**a) Add import (after the lucide-react import on line 2):**
```typescript
import VoiceRecordButton from '@/components/VoiceRecordButton'
```

**b) Insert VoiceRecordButton before the "添加碎片" header.** Find the `<section>` for the right panel (around line 265):

Current:
```typescript
        <section className="prism-panel flex min-h-0 flex-col rounded-lg p-3">
          <div className="mb-3 flex items-center gap-2">
```

Replace with:
```typescript
        <section className="prism-panel flex min-h-0 flex-col rounded-lg p-3">
          {/* Voice recording / upload area */}
          <div className="mb-3">
            <VoiceRecordButton
              onResult={(item) => {
                setItems((current) => [item, ...current])
                setActiveId(item.id)
                setNotice('语音已转写并放入收件箱，等待确认入库。')
              }}
              onError={(msg) => setError(msg)}
            />
          </div>

          <div className="mb-3 flex items-center gap-2">
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/InboxPage.tsx
git commit -m "feat: embed VoiceRecordButton in InboxPage

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: End-to-End Verification

**Files:**
- No new files.

- [ ] **Step 1: Run all new backend tests**

Run: `cd backend && python -m pytest tests/test_asr.py tests/test_asset_voice.py -v`
Expected: All tests PASS

- [ ] **Step 2: Run all existing backend tests to check for regressions**

Run: `cd backend && python -m pytest -x -v`
Expected: No new failures

- [ ] **Step 3: Verify frontend builds**

Run: `cd frontend && npx tsc --noEmit && npx vite build`
Expected: Build succeeds

- [ ] **Step 4: Manual smoke test checklist**

(Perform these manually after deployment)
- [ ] Navigate to `/inbox`
- [ ] See "语音录入" area with microphone button and upload hint
- [ ] Click mic button → see recording state with timer
- [ ] Click stop → see processing state
- [ ] After processing → see new item in inbox list with `voice` source type
- [ ] Drag an audio file to the drop zone → see processing → new item appears
- [ ] Confirm/reject the voice-generated item works as normal

- [ ] **Step 5: Commit (if any fixes)**

```bash
git add -u
git commit -m "fix: address issues found during E2E verification

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Dependency Order

```
Task 1 (Config) ──┐
                  ├──> Task 3 (Endpoint) ──> Task 7 (E2E Verify)
Task 2 (ASR)  ────┘
                                 Task 4 (API fn) ──> Task 5 (Component) ──> Task 6 (InboxPage) ──┘
```

Tasks 1+2 can run in parallel. Task 3 depends on 1+2. Tasks 4→5→6 are sequential. Task 7 is last.
