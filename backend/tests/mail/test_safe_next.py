import pytest

from app.mail.connections import safe_next


@pytest.mark.parametrize("v", ["/register?type=tool", "/e/12/plan#x", "/"])
def test_same_site_paths_are_kept(v):
    assert safe_next(v) == v


@pytest.mark.parametrize(
    "v",
    ["//evil.example/x", "https://evil.example/x", "/\\evil.example", "/..//evil.example/x", "/./..//evil.example", "/a/../..//evil.example", "/%2e%2e//evil.example", "/%2E.//evil.example", None, "register"],
)
def test_paths_that_could_leave_the_site_are_dropped(v):
    assert safe_next(v) is None
