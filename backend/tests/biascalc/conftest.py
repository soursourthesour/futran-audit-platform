import pytest

from tests.initiation.conftest import live, people, submitted  # noqa: F401
from tests.inventory.test_named_users import inv  # noqa: F401
from tests.scoring.test_service import ats  # noqa: F401


def applicant_csv(cells: dict[tuple[str, str], tuple[int, int]], unknown: tuple[int, int] = (0, 0), header: str = "id,selected,sex,race_ethnicity") -> bytes:
    """One row per applicant: (sex, race label) -> (applicants, selected); `unknown` rows have neither sex nor race."""
    lines, n = [header], 0
    for (sex, race), (total, sel) in cells.items():
        for i in range(total):
            n += 1
            lines.append(f"A{n:05d},{'yes' if i < sel else 'no'},{sex},{race}")
    for i in range(unknown[0]):
        n += 1
        lines.append(f"A{n:05d},{'yes' if i < unknown[1] else 'no'},,")
    return ("\n".join(lines) + "\n").encode()


# Sex: male 50/100, female 30/80 (0.75). Race: White 50/100, Hispanic or Latino 30/80 (0.75). Intersectional: Hispanic or
# Latino female 10/40 against 0.50 (0.50, the lowest). 20 of 200 people (10%) have no sex or race recorded.
SMALL = {("Male", "White"): (60, 30), ("Female", "White"): (40, 20), ("Male", "Hispanic or Latino"): (40, 20), ("Female", "Hispanic or Latino"): (40, 10)}


@pytest.fixture
def small_csv():
    return applicant_csv(SMALL, unknown=(20, 5))
