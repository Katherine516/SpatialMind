import os

try:
    from celery import Celery
except ImportError:  # pragma: no cover - dependency-light development path
    Celery = None  # type: ignore


if Celery is not None:
    app = Celery("spatialmind", broker=os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
else:
    app = None
