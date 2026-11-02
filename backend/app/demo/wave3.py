"""Demo data for the wave 3 extended features (spec §21, screens 25–35).

Each workstream writes `app/demo/wave3_<ws>.py` with `seed(m, ids) -> dict | None`, where `m` is the in-process API
driver from `seed_demo` and `ids` holds the client ids the earlier steps returned. Steps run in this order; a step whose
module is not there yet is skipped, so workstreams can land in any order.
"""
import importlib

from app.demo.seed_demo import Demo

STEPS = ["wave3_g", "wave3_h", "wave3_i", "wave3_j", "wave3_k", "wave3_l"]


def seed(m: Demo, ids: dict) -> dict:
    out: dict = {}
    for name in STEPS:
        try:
            mod = importlib.import_module(f"app.demo.{name}")
        except ModuleNotFoundError as e:
            if e.name != f"app.demo.{name}":
                raise
            continue
        out |= mod.seed(m, dict(ids) | out) or {}
    return out
