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
        """ASR returns empty text, returns empty string — caller decides how to handle."""
        from backend.app.services.asr import transcribe

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
            result = await transcribe(
                provider="dashscope",
                api_key="sk-test-key",
                model="paraformer-v2",
                audio_path=tmp_path,
            )
            assert result == ""
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

    @pytest.mark.asyncio
    async def test_transcribe_auth_failed(self, monkeypatch):
        """Mock 401 response, verify ASRError with API Key 无效."""
        from backend.app.services.asr import transcribe, ASRError

        submit_response = MagicMock()
        submit_response.status_code = 401

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = submit_response

        monkeypatch.setattr(
            "backend.app.services.asr.httpx.AsyncClient",
            lambda **kwargs: mock_client,
        )

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tf:
            tf.write(b"fake audio data")
            tmp_path = tf.name

        try:
            with pytest.raises(ASRError) as exc_info:
                await transcribe(
                    provider="dashscope",
                    api_key="sk-bad-key",
                    model="paraformer-v2",
                    audio_path=tmp_path,
                )
            assert "API Key 无效" in str(exc_info.value)
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_transcribe_poll_timeout(self, monkeypatch):
        """Mock all polls return PENDING, verify ASRError with 语音识别超时."""
        from backend.app.services.asr import transcribe, ASRError

        submit_response = MagicMock()
        submit_response.status_code = 200
        submit_response.json.return_value = {"output": {"task_id": "task-timeout"}}

        poll_pending = MagicMock()
        poll_pending.status_code = 200
        poll_pending.json.return_value = {
            "output": {"task_status": "PENDING"}
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = submit_response
        mock_client.get.return_value = poll_pending

        monkeypatch.setattr(
            "backend.app.services.asr.httpx.AsyncClient",
            lambda **kwargs: mock_client,
        )

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tf:
            tf.write(b"fake audio data")
            tmp_path = tf.name

        try:
            with pytest.raises(ASRError) as exc_info:
                await transcribe(
                    provider="dashscope",
                    api_key="sk-test-key",
                    model="paraformer-v2",
                    audio_path=tmp_path,
                )
            assert "语音识别超时" in str(exc_info.value)
        finally:
            os.unlink(tmp_path)

    @pytest.mark.asyncio
    async def test_transcribe_task_cancelled(self, monkeypatch):
        """Mock poll returns CANCELED status, verify ASRError."""
        from backend.app.services.asr import transcribe, ASRError

        submit_response = MagicMock()
        submit_response.status_code = 200
        submit_response.json.return_value = {"output": {"task_id": "task-cancel"}}

        poll_cancelled = MagicMock()
        poll_cancelled.status_code = 200
        poll_cancelled.json.return_value = {
            "output": {
                "task_status": "CANCELED",
                "message": "Task cancelled by user",
            }
        }

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.post.return_value = submit_response
        mock_client.get.return_value = poll_cancelled

        monkeypatch.setattr(
            "backend.app.services.asr.httpx.AsyncClient",
            lambda **kwargs: mock_client,
        )

        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tf:
            tf.write(b"fake audio data")
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
