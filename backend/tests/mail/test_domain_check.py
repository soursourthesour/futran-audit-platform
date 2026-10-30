import httpx

from app.mail.domain_check import check_domain


def test_spf_dkim_and_dmarc_are_read_from_dns_txt_records():
    def handler(req: httpx.Request):
        name, typ = req.url.params["name"], req.url.params["type"]
        answers = {
            ("abc.com", "TXT"): ['"v=spf1 include:spf.protection.outlook.com -all"'],
            ("_dmarc.abc.com", "TXT"): ['"v=DMARC1; p=quarantine"'],
            ("selector1._domainkey.abc.com", "CNAME"): ["selector1-abc-com._domainkey.abc.onmicrosoft.com."],
        }.get((name, typ), [])
        return httpx.Response(200, json={"Status": 0, "Answer": [{"data": a} for a in answers]})

    r = check_domain("abc.com", "microsoft365", transport=httpx.MockTransport(handler))
    assert r == {"spf_ok": True, "dkim_ok": True, "dmarc_ok": True}


def test_missing_records_are_reported_as_not_ok():
    r = check_domain("abc.com", "google", transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"Status": 3})))
    assert r == {"spf_ok": False, "dkim_ok": False, "dmarc_ok": False}


def test_a_lookup_failure_leaves_the_result_unknown():
    def boom(req):
        raise httpx.ConnectError("offline")

    assert check_domain("abc.com", "google", transport=httpx.MockTransport(boom)) == {"spf_ok": None, "dkim_ok": None, "dmarc_ok": None}
