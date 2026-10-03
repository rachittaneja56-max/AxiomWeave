"""One-job-at-a-time worker for bounded media CPU tasks."""

import asyncio
import socket
from uuid import uuid4

from sqlalchemy.orm import Session, sessionmaker

from app.job_queue import DEFAULT_LEASE_SECONDS, MEDIA_CPU, claim_next_job
from app.media_workflows import process_media_task

DEFAULT_POLL_SECONDS = 1.0


def process_one_media_job(
    session_factory: sessionmaker[Session],
    worker_id: str,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> bool:
    with session_factory() as session:
        claim = claim_next_job(session, MEDIA_CPU, worker_id, lease_seconds)
    if claim is None:
        return False
    return process_media_task(session_factory, claim)


async def run_media_worker(
    session_factory: sessionmaker[Session],
    worker_id: str,
    once: bool = False,
) -> None:
    while True:
        processed = process_one_media_job(session_factory, worker_id)
        if once:
            return
        if not processed:
            await asyncio.sleep(DEFAULT_POLL_SECONDS)


def media_worker_id() -> str:
    return f"{socket.gethostname()}:media:{uuid4().hex[:12]}"
