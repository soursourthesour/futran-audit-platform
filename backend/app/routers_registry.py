"""Collect every domain's APIRouter. Each entry is a dotted module with a `router`."""
import importlib

from fastapi import APIRouter

ROUTER_MODULES: list[str] = ["auth.router"]


def api_routers() -> list[APIRouter]:
    return [importlib.import_module(f"app.{m}").router for m in ROUTER_MODULES]
