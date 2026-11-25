"""OBS-K1: the campaign rules the mail module applies (no attestation email for a closed campaign, who has already
answered, what a personal link opens) were registered only when the routers imported the campaign modules. A job
runner or CLI that never loads the routers sent after an early close. The mail module now loads them itself."""
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

SCRIPT = """
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.core.models import Base
import app.models_registry
from app.mail import sending
assert not any(m in sys.modules for m in ("app.routers_registry", "app.main")), "the routers were loaded"
eng = create_engine("sqlite://")
Base.metadata.create_all(eng)
with Session(eng) as db:
    print(repr(sending.campaign_closed(db, "attestation", None)))
print(sorted(sending.RESPONDED), sorted(sending.LINK_PURPOSES))
"""


def test_the_campaign_rules_apply_without_the_routers():
    env = {**os.environ, "PYTHONPATH": str(BACKEND)}
    out = subprocess.run([sys.executable, "-c", SCRIPT], cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    closed, kinds = out.stdout.strip().splitlines()
    assert "no attestation campaign" in closed
    assert kinds == "['attestation', 'policy_ack', 'training'] ['attestation', 'policy_ack', 'training']"
