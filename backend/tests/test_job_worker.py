import asyncio

import pytest

from app import job_worker
from app.job_worker import run_worker


def test_once_with_empty_queue_returns_after_one_claim_opportunity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def no_job(*_args: object, **_kwargs: object) -> bool:
        nonlocal calls
        calls += 1
        return False

    monkeypatch.setattr(job_worker, "process_one_job", no_job)

    asyncio.run(run_worker(None, None, "test-worker", once=True))  # type: ignore[arg-type]

    assert calls == 1


def test_once_with_work_processes_at_most_one_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def one_job(*_args: object, **_kwargs: object) -> bool:
        nonlocal calls
        calls += 1
        return True

    monkeypatch.setattr(job_worker, "process_one_job", one_job)

    asyncio.run(run_worker(None, None, "test-worker", once=True))  # type: ignore[arg-type]

    assert calls == 1


def test_continuous_worker_waits_when_empty_then_processes_later_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StopWorker(Exception):
        pass

    calls = 0
    work_available = False
    processed_jobs = 0
    sleeps: list[float] = []

    async def return_work_when_available(*_args: object, **_kwargs: object) -> bool:
        nonlocal calls, processed_jobs
        calls += 1
        if calls == 1:
            assert not work_available
            return False
        if calls == 2:
            assert work_available
            processed_jobs += 1
            return True
        raise StopWorker

    async def make_work_available(seconds: float) -> None:
        nonlocal work_available
        sleeps.append(seconds)
        work_available = True

    monkeypatch.setattr(job_worker, "process_one_job", return_work_when_available)
    monkeypatch.setattr(job_worker.asyncio, "sleep", make_work_available)

    with pytest.raises(StopWorker):
        asyncio.run(run_worker(None, None, "test-worker"))  # type: ignore[arg-type]

    assert calls == 3
    assert sleeps == [job_worker.DEFAULT_POLL_SECONDS]
    assert processed_jobs == 1


def test_continuous_worker_keeps_job_processing_sequential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StopWorker(Exception):
        pass

    real_sleep = asyncio.sleep
    calls = 0
    in_flight = 0
    max_in_flight = 0

    async def process_sequentially(*_args: object, **_kwargs: object) -> bool:
        nonlocal calls, in_flight, max_in_flight
        calls += 1
        if calls == 3:
            raise StopWorker
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        try:
            await real_sleep(0)
            return True
        finally:
            in_flight -= 1

    monkeypatch.setattr(job_worker, "process_one_job", process_sequentially)

    with pytest.raises(StopWorker):
        asyncio.run(run_worker(None, None, "test-worker"))  # type: ignore[arg-type]

    assert calls == 3
    assert max_in_flight == 1
