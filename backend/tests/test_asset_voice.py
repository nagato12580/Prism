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
