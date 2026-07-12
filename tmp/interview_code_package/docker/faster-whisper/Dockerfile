# faster-whisper ASR service
# small model (~488MB) — good Chinese accuracy, runs on CPU
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    faster-whisper==1.0.3 \
    fastapi==0.115.6 \
    uvicorn[standard]==0.34.0 \
    python-multipart==0.0.20 \
    requests

# Pre-download model on build so startup is instant
RUN python -c "from faster_whisper import WhisperModel; \
    WhisperModel('small', device='cpu', compute_type='int8', download_root='/app/models')"

COPY service.py .

EXPOSE 5199

CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "5199"]
