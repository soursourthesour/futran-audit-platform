"""A person's job level at their company (11-03 review, C6). Stored as a key on User.job_level; null means not given."""

JOB_LEVELS: dict[str, str] = {
    "executive": "Executive",
    "department_head": "Department head",
    "manager": "Manager",
    "level_3": "Level 3",
    "level_2": "Level 2",
    "level_1": "Level 1",
}

NOT_A_LEVEL = f"Job level must be one of: {', '.join(JOB_LEVELS.values())}."


def _norm(text: str) -> str:
    return " ".join(str(text).replace("_", " ").split()).casefold()


_LOOKUP = {_norm(k): k for k in JOB_LEVELS} | {_norm(v): k for k, v in JOB_LEVELS.items()}


def parse_job_level(value) -> str | None:
    """The key for a key or label (any case and spacing); "" and None give None. Raises ValueError otherwise."""
    if value is None or not str(value).strip():
        return None
    key = _LOOKUP.get(_norm(value))
    if key is None:
        raise ValueError(NOT_A_LEVEL)
    return key


def job_level_label(key: str | None) -> str | None:
    return JOB_LEVELS.get(key) if key else None
