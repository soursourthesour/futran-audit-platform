"""CSV written with the csv module, with spreadsheet formulas neutralised (OWASP CSV injection)."""
import csv
import io

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value) -> str:
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(FORMULA_START) else s


def to_csv(header: list[str], rows: list[list]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow([safe_cell(v) for v in r])
    return buf.getvalue()
