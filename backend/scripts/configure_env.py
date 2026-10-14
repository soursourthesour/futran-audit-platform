"""First-run configuration for Windows laptops (called by setup.bat).

- Creates .env from .env.example and generates a SECRET_KEY.
- Keeps the database and stored files in %LOCALAPPDATA%\\FutranAuditPlatform rather than in the project folder,
  so OneDrive never syncs a live database (which can corrupt it).
"""
import os
import re
import secrets
import shutil
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
env = root / ".env"
if not env.exists():
    shutil.copy(root / ".env.example", env)
text = env.read_text(encoding="utf-8")

data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "FutranAuditPlatform" / "data"
(data / "files").mkdir(parents=True, exist_ok=True)


def setting(name: str, value: str, only_if: str | None = None) -> None:
    global text
    pattern = re.compile(rf"^{name}=(.*)$", re.M)
    m = pattern.search(text)
    if m is None:
        text += f"\n{name}={value}\n"
    elif only_if is None or m.group(1).strip() == only_if:
        text = text[: m.start()] + f"{name}={value}" + text[m.end():]


setting("SECRET_KEY", secrets.token_urlsafe(48), only_if="change-me")
setting("DATABASE_URL", "sqlite:///" + (data / "app.db").as_posix(), only_if="sqlite:///./data/app.db")
setting("FILE_STORE", "local:" + (data / "files").as_posix(), only_if="local:./data/files")
env.write_text(text, encoding="utf-8")
print(f"Data folder: {data}")
sys.exit(0)
