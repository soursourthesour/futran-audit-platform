"""Virus scanning on upload (spec §16). ClamAV is a post-build item (schematic §14); until then files are marked
not_scanned, except that the standard EICAR test signature is always caught so the rejection path can be tested."""
from app.core.config import Settings

EICAR = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"


def scan(data: bytes, settings: Settings) -> str:
    if EICAR in data[:4096]:
        return "infected"
    if settings.virus_scan == "clamav":
        raise NotImplementedError("ClamAV scanning is not connected yet. Set VIRUS_SCAN=off.")
    return "not_scanned"
