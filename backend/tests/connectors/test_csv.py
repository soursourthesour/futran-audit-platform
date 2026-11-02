"""Expense and CASB/proxy CSV uploads (spec §21 F2): matched to the AI vendor list and aggregated to tool × department.
Browsing data never keeps a person."""
import pytest

from app.connectors import csvparse
from app.core.errors import Invalid

EXPENSE = """Date,Employee,Email,Department,Merchant,Description,Amount
2026-10-02,Ana Ruiz,ana.ruiz@abc.test,Sales and Marketing,OpenAI,OPENAI *CHATGPT SUBSCR,20.00
2026-10-03,Ben Okafor,ben.okafor@abc.test,Sales and Marketing,OpenAI,OPENAI *CHATGPT SUBSCR,20.00
2026-11-02,Ana Ruiz,ana.ruiz@abc.test,Sales and Marketing,OpenAI,OPENAI *CHATGPT SUBSCR,20.00
2026-10-04,Hiro Tanaka,hiro.tanaka@abc.test,Engineering and IT,Anthropic,CLAUDE.AI SUBSCRIPTION,20.00
2026-10-05,Hiro Tanaka,hiro.tanaka@abc.test,Engineering and IT,Staples,STAPLES 0042 OFFICE,54.10
"""

CASB = """timestamp,user,department,destination_host,requests
2026-10-01T09:00,u1@abc.test,Operations,chatgpt.com,40
2026-10-01T09:05,u2@abc.test,Operations,chatgpt.com,10
2026-10-01T09:07,u1@abc.test,Operations,chatgpt.com,5
2026-10-01T10:00,u3@abc.test,Finance,claude.ai,7
2026-10-01T10:00,u3@abc.test,Finance,www.bbc.co.uk,99
"""


def test_expense_rows_match_vendors_and_aggregate_by_department():
    out = csvparse.parse_expense(EXPENSE.encode())
    assert (out.rows_read, out.rows_matched) == (5, 4)
    by = {(o.vendor_key, o.department): o for o in out.observations}
    chat = by[("openai_chatgpt", "Sales and Marketing")]
    assert chat.signal == "expense" and chat.user_count == 2 and chat.detail == "2 paid subscriptions"
    assert set(chat.people) == {"ana.ruiz@abc.test", "ben.okafor@abc.test"}
    assert by[("anthropic_claude", "Engineering and IT")].detail == "1 paid subscription"


def test_expense_needs_a_description_or_merchant_column():
    with pytest.raises(Invalid) as exc:
        csvparse.parse_expense(b"Date,Amount\n2026-10-01,20\n")
    assert "description" in exc.value.errors[0]["message"].lower()


def test_casb_rows_are_aggregated_and_keep_no_person():
    out = csvparse.parse_casb(CASB.encode())
    assert (out.rows_read, out.rows_matched) == (5, 4)
    by = {(o.vendor_key, o.department): o for o in out.observations}
    ops = by[("openai_chatgpt", "Operations")]
    assert ops.signal == "traffic" and ops.user_count == 2 and ops.detail == "55 requests"
    assert all(o.people is None for o in out.observations)


def test_casb_needs_a_domain_column():
    with pytest.raises(Invalid):
        csvparse.parse_casb(b"user,department\nu1,Ops\n")


def test_csv_with_a_byte_order_mark_and_semicolons_is_read():
    data = ("﻿Merchant;Department\nOPENAI *CHATGPT;Legal\n").encode("utf-8")
    out = csvparse.parse_expense(data)
    assert out.rows_matched == 1 and out.observations[0].department == "Legal" and out.observations[0].user_count == 1
