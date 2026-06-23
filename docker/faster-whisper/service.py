"""faster-whisper ASR service — FastAPI + faster-whisper small model.

POST /transcribe  — multipart audio file upload → {"text": "..."}
GET  /health       — {"status": "ok", "model_loaded": true}
"""
import os
import tempfile
from contextlib import asynccontextmanager

from faster_whisper import WhisperModel
from fastapi import FastAPI, File, HTTPException, UploadFile

MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "small")
MODEL_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
MODEL_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")

_model: WhisperModel | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model
    _model = WhisperModel(
        MODEL_SIZE,
        device=MODEL_DEVICE,
        compute_type=MODEL_COMPUTE,
        download_root="/app/models",
    )
    yield
    _model = None


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": _model is not None}


@app.post("/transcribe")
async def transcribe_endpoint(file: UploadFile = File(...)):
    """Transcribe audio file. Returns {"text": "..."}"""
    if _model is None:
        raise HTTPException(status_code=503, detail="Model not loaded yet")

    # Save uploaded file to temp path (faster-whisper needs a file path)
    suffix = os.path.splitext(file.filename or "audio.webm")[1] or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    try:
        segments, info = _model.transcribe(
            tmp_path,
            language=None,  # auto-detect
            beam_size=5,
            vad_filter=True,  # filter silence
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        text = "".join(seg.text for seg in segments).strip()
        return {"text": text}
    finally:
        os.unlink(tmp_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("service:app", host="0.0.0.0", port=5199, reload=False)
