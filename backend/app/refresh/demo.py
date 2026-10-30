"""The fake Claude client used by the demo and the browser tests (REFRESH_CLIENT=fake). It never calls the network.
Its proposals are labelled as demo proposals so nobody mistakes them for research."""
from app.refresh.claude import FakeRefreshClient


def demo_client() -> FakeRefreshClient:
    return FakeRefreshClient(replies={}, model="fake-claude (demo)")
