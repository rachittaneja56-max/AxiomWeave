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


def test_combined_worker_processes_only_available_model_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import media_worker

    calls: list[str] = []

    async def model_job(*_args: object, **_kwargs: object) -> bool:
        calls.append("model_io")
        return True

    def media_job(*_args: object, **_kwargs: object) -> bool:
        calls.append("media_cpu")
        return False

    monkeypatch.setattr(job_worker, "process_one_job", model_job)
    monkeypatch.setattr(media_worker, "process_one_media_job", media_job)

    asyncio.run(job_worker.run_combined_worker(None, None, "test-worker", once=True))  # type: ignore[arg-type]

    assert calls == ["model_io"]


def test_combined_worker_falls_through_to_only_available_media_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import media_worker

    calls: list[str] = []

    async def no_model_job(*_args: object, **_kwargs: object) -> bool:
        calls.append("model_io")
        return False

    def media_job(*_args: object, **_kwargs: object) -> bool:
        calls.append("media_cpu")
        return True

    monkeypatch.setattr(job_worker, "process_one_job", no_model_job)
    monkeypatch.setattr(media_worker, "process_one_media_job", media_job)

    asyncio.run(job_worker.run_combined_worker(None, None, "test-worker", once=True))  # type: ignore[arg-type]

    assert calls == ["model_io", "media_cpu"]


def test_combined_worker_checks_both_empty_queues_and_keeps_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import media_worker

    class StopWorker(Exception):
        pass

    calls: list[str] = []
    sleeps: list[float] = []

    async def no_model_job(*_args: object, **_kwargs: object) -> bool:
        calls.append("model_io")
        return False

    def no_media_job(*_args: object, **_kwargs: object) -> bool:
        calls.append("media_cpu")
        return False

    async def stop_after_two_polls(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise StopWorker

    monkeypatch.setattr(job_worker, "process_one_job", no_model_job)
    monkeypatch.setattr(media_worker, "process_one_media_job", no_media_job)
    monkeypatch.setattr(job_worker.asyncio, "sleep", stop_after_two_polls)

    with pytest.raises(StopWorker):
        asyncio.run(job_worker.run_combined_worker(None, None, "test-worker"))  # type: ignore[arg-type]

    assert calls == ["model_io", "media_cpu", "model_io", "media_cpu"]
    assert sleeps == [job_worker.DEFAULT_POLL_SECONDS] * 2


def test_combined_worker_processes_model_and_media_jobs_sequentially(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import media_worker

    real_sleep = asyncio.sleep
    processed: list[str] = []
    in_flight = 0
    max_in_flight = 0
    model_available = True
    media_available = True

    async def model_job(*_args: object, **_kwargs: object) -> bool:
        nonlocal in_flight, max_in_flight, model_available
        if not model_available:
            return False
        model_available = False
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        try:
            await real_sleep(0)
            processed.append("model_io")
            return True
        finally:
            in_flight -= 1

    def media_job(*_args: object, **_kwargs: object) -> bool:
        nonlocal in_flight, max_in_flight, media_available
        if not media_available:
            return False
        media_available = False
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        try:
            processed.append("media_cpu")
            return True
        finally:
            in_flight -= 1

    async def stop_after_both_jobs(seconds: float) -> None:
        assert seconds == job_worker.DEFAULT_POLL_SECONDS
        raise RuntimeError("both queues were inspected after processing")

    monkeypatch.setattr(job_worker, "process_one_job", model_job)
    monkeypatch.setattr(media_worker, "process_one_media_job", media_job)
    monkeypatch.setattr(job_worker.asyncio, "sleep", stop_after_both_jobs)

    with pytest.raises(RuntimeError, match="both queues were inspected"):
        asyncio.run(job_worker.run_combined_worker(None, None, "test-worker"))  # type: ignore[arg-type]

    assert processed == ["model_io", "media_cpu"]
    assert max_in_flight == 1


def test_combined_worker_alternates_preference_when_both_queues_are_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import media_worker

    class StopWorker(Exception):
        pass

    calls: list[str] = []

    async def model_job(*_args: object, **_kwargs: object) -> bool:
        calls.append("model_io")
        if calls.count("model_io") == 3:
            raise StopWorker
        return True

    def media_job(*_args: object, **_kwargs: object) -> bool:
        calls.append("media_cpu")
        return True

    monkeypatch.setattr(job_worker, "process_one_job", model_job)
    monkeypatch.setattr(media_worker, "process_one_media_job", media_job)

    with pytest.raises(StopWorker):
        asyncio.run(job_worker.run_combined_worker(None, None, "test-worker"))  # type: ignore[arg-type]

    assert calls == ["model_io", "media_cpu", "model_io", "media_cpu", "model_io"]


def test_combined_worker_once_processes_at_most_one_job_across_both_queues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import media_worker

    calls: list[str] = []

    async def model_job(*_args: object, **_kwargs: object) -> bool:
        calls.append("model_io")
        return True

    def media_job(*_args: object, **_kwargs: object) -> bool:
        calls.append("media_cpu")
        return True

    monkeypatch.setattr(job_worker, "process_one_job", model_job)
    monkeypatch.setattr(media_worker, "process_one_media_job", media_job)

    asyncio.run(job_worker.run_combined_worker(None, None, "test-worker", once=True))  # type: ignore[arg-type]

    assert calls == ["model_io"]


def test_media_only_worker_once_still_processes_at_most_one_media_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import media_worker

    calls = 0

    def media_job(*_args: object, **_kwargs: object) -> bool:
        nonlocal calls
        calls += 1
        return True

    monkeypatch.setattr(media_worker, "process_one_media_job", media_job)

    asyncio.run(media_worker.run_media_worker(None, "test-worker", once=True))  # type: ignore[arg-type]

    assert calls == 1
