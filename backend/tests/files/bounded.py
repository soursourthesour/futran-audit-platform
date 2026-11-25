"""Shared probe for BUG-H04: record every UploadFile.read a request makes, to prove a route never reads a whole upload."""
from contextlib import contextmanager

from starlette.datastructures import UploadFile


@contextmanager
def record_reads(monkeypatch):
    calls: list[tuple[int, int]] = []  # (size asked for, bytes returned)
    real = UploadFile.read

    async def probe(self, size: int = -1):
        data = await real(self, size)
        calls.append((size, len(data)))
        return data

    monkeypatch.setattr(UploadFile, "read", probe)
    yield calls


def assert_bounded(calls, limit_bytes: int) -> None:
    assert calls, "the route did not read the upload through UploadFile.read"
    assert all(size > 0 for size, _ in calls), f"unbounded read: {calls}"
    assert sum(n for _, n in calls) <= limit_bytes + 1, f"read past the limit: {calls}"
