"""Deterministic answers for the in-process fake model (tests, demo, browser tests). Each handler reads the same
context the prompt was built from and only ever quotes text it was given, so its suggestions pass the quote check."""


def answer(task: str, context: dict) -> dict:
    handler = HANDLERS.get(task)
    return handler(context) if handler else {}


HANDLERS: dict = {}
