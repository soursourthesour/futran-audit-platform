"""Futran AI literacy modules (spec §21 F12): five structured modules with short quizzes, and a SCORM 1.2 export."""
import io
import zipfile
from xml.etree import ElementTree

from app.training import modules as M

CODES = {"acceptable_use", "shadow_ai", "human_oversight", "bias_basics_hr", "prompt_hygiene"}


def test_five_modules_each_with_pages_and_a_quiz():
    lib = M.library()
    assert set(lib) == CODES
    for m in lib.values():
        assert m["version"] and m["minutes"] > 0 and m["pages"] and len(m["quiz"]) >= 3
        assert 50 <= m["pass_mark"] <= 100
        for q in m["quiz"]:
            ids = [o["id"] for o in q["options"]]
            assert q["answer"] in ids and len(ids) == len(set(ids)) and q["explanation"], (m["code"], q["id"])


def test_company_name_is_filled_in_and_answers_are_not_sent_to_the_learner():
    view = M.learner_view(M.library()["acceptable_use"], "ABC Corp")
    assert view["title"] == "AI acceptable use at ABC Corp"
    assert "{company}" not in str(view)
    assert all("answer" not in q and "explanation" not in q for q in view["quiz"])


def test_scoring():
    m = M.library()["bias_basics_hr"]
    right = {q["id"]: q["answer"] for q in m["quiz"]}
    assert M.score(m, right) == 100
    wrong = dict(right) | {m["quiz"][0]["id"]: "zz"}
    assert M.score(m, wrong) == round(100 * (len(right) - 1) / len(right))


def test_scorm_12_package():
    data = M.scorm_zip(M.library()["shadow_ai"], "ABC Corp")
    z = zipfile.ZipFile(io.BytesIO(data))
    assert {"imsmanifest.xml", "index.html"} <= set(z.namelist())
    root = ElementTree.fromstring(z.read("imsmanifest.xml"))
    ns = {"cp": "http://www.imsproject.org/xsd/imscp_rootv1p1p2", "adlcp": "http://www.adlnet.org/xsd/adlcp_rootv1p2"}
    assert root.find("cp:metadata/cp:schemaversion", ns).text == "1.2"
    res = root.find("cp:resources/cp:resource", ns)
    assert res.get("{http://www.adlnet.org/xsd/adlcp_rootv1p2}scormtype") == "sco" and res.get("href") == "index.html"
    assert root.find("cp:organizations/cp:organization/cp:item/adlcp:masteryscore", ns).text == "80"
    html = z.read("index.html").decode()
    assert "LMSInitialize" in html and "cmi.core.score.raw" in html and "cmi.core.lesson_status" in html and "LMSFinish" in html
    assert "Shadow AI and data leakage" in html and "</script><" not in html.split("<script>")[1].split("</script>")[0]
