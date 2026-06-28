import json

import redis

from engine.app.config import settings


def redis_client():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def push_job(client, queue_name: str, job_id: str):
    client.lpush(queue_name, json.dumps({"job_id": job_id}))


def pop_job(client, queue_name: str, timeout_seconds: int = 2):
    result = client.brpop(queue_name, timeout=timeout_seconds)
    if result is None:
        return None
    _queue_name, payload = result
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    data = json.loads(payload)
    return data.get("job_id")
