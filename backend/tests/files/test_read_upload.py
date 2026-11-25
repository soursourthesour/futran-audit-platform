"""BUG-H04: uploads are read in chunks and never past the limit, through one helper."""
import asyncio
import io
import re
from pathlib import Path

from starlette.datastructures import UploadFile

from app.files.service import read_upload

APP = Path(__file__).resolve().parents[2] / "app"


class _Endless(io.RawIOBase):
    """A file that never ends and counts what was taken from it."""
    def __init__(self):
        self.taken = 0

    def readable(self):
        return True

    def readinto(self, b):
        n = len(b)
        b[:n] = b"x" * n
        self.taken += n
        return n


def test_reads_one_byte_past_the_limit_and_stops():
    src = _Endless()
    data = asyncio.run(read_upload(UploadFile(file=src, filename="big.pdf"), 3 * 1024 * 1024 + 7))
    assert len(data) == 3 * 1024 * 1024 + 8
    assert src.taken == len(data)


def test_a_small_file_is_read_whole():
    data = asyncio.run(read_upload(UploadFile(file=io.BytesIO(b"hello"), filename="a.txt"), 10))
    assert data == b"hello"


def test_no_route_reads_a_whole_upload():
    """await file.read() with no size loads the entire request body; use files.service.read_upload."""
    offenders = []
    for p in APP.rglob("*.py"):
        for i, line in enumerate(p.read_text().splitlines(), 1):
            if re.search(r"\b(file|upload|f)\.read\(\s*\)", line) and "await" in line:
                offenders.append(f"{p.relative_to(APP)}:{i}")
            if re.search(r"\.file\.read\(\s*\)", line):
                offenders.append(f"{p.relative_to(APP)}:{i}")
    assert offenders == []
