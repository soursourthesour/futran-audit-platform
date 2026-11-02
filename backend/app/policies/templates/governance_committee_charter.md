---
code: governance_committee_charter
version: "1.0"
title: AI Governance Committee Charter
summary: Establishes the AI governance committee — its authority, membership, quorum, decisions, records and reporting line.
catalog_codes: [GR-01, GD-02]
questions:
  - {key: company_name, label: Company name, type: text, required: true, help: "The organization's name as staff know it. It appears in the title and throughout the text."}
  - {key: policy_owner, label: Policy owner, type: text, required: true, help: "Name and job title of the person who keeps this document current and answers questions about it, for example Maria Lopez, Chief AI Compliance Officer."}
  - {key: approving_body, label: Approved by, type: text, required: true, default: "AI governance committee", help: "The body or person that approves this document and any later change to it."}
  - {key: review_cycle, label: Review cycle, type: choice, default: annually, options: [{value: annually, label: Annually}, {value: six_months, label: Every six months}], help: "How often the document is reviewed. The review date is set when the document is published, and a monitoring check flags it when the date passes."}
  - {key: chair, label: Chair, type: text, required: true, default: "Chief Operating Officer", help: "The role that chairs the committee. Use a role rather than a name so the charter survives a change of person."}
  - {key: deputy_chair, label: Deputy chair, type: text, required: true, default: "Chief AI Compliance Officer", help: "The role that chairs meetings when the chair is absent."}
  - {key: members, label: Members, type: list, required: true, default: ["Chief AI Compliance Officer", "Data Protection Officer", "Chief Information Security Officer", "Head of HR", "General Counsel", "Head of IT"], help: "One role per line. Include privacy, security, legal and the business functions that use AI the most."}
  - key: meeting_frequency
    label: Meets
    type: choice
    default: quarterly
    options: [{value: monthly, label: Monthly}, {value: quarterly, label: Quarterly}]
    help: "How often the committee meets as a minimum. The chair can call extra meetings."
  - key: decisions
    label: The committee decides
    type: multi
    required: true
    default: [policy, high_risk, risk_acceptance, vendors, incidents]
    options:
      - {value: policy, label: Approval of AI policies and procedures}
      - {value: high_risk, label: Approval of high-risk (Tier 3) AI systems before use}
      - {value: risk_acceptance, label: Acceptance of residual AI risk above the risk appetite}
      - {value: vendors, label: Approval of new AI vendors for high-risk use}
      - {value: incidents, label: Oversight of serious AI incidents and their follow-up}
    help: "The decisions reserved to the committee. Anything not listed is decided by the accountable owner of the system."
  - {key: reports_to, label: Reports to, type: text, required: true, default: "the board of directors", help: "Who receives the committee's report, for example the board or the executive leadership team."}
---
# {{ company_name }} AI Governance Committee Charter

## 1. Purpose

The AI governance committee oversees how {{ company_name }} develops, buys and uses artificial intelligence. It makes sure AI risk is identified, assessed and managed within the risk appetite set by {{ reports_to }}, and that the company meets the laws and commitments that apply to its use of AI.

## 2. Authority

The committee acts under the authority of {{ reports_to }}. It may ask any employee for information, ask for an AI system to be paused while a concern is investigated, and obtain independent advice at the company's expense within the budget agreed each year.

## 3. Membership

The committee is chaired by the {{ chair }}, with the {{ deputy_chair }} as deputy chair. Its members are:

{% for m in members %}
- {{ m }}
{% endfor %}

Members may send a named deputy who can decide on their behalf. The chair may invite others to attend for particular items; they do not vote.

## 4. Meetings and quorum

The committee meets {{ "every month" if meeting_frequency == "monthly" else "every quarter" }}, and the chair may call extra meetings when needed. A meeting is quorate when a majority of members, including the chair or deputy chair, are present. Decisions are taken by consensus; where consensus cannot be reached the chair decides and the dissent is recorded.

## 5. Decisions reserved to the committee

{% for d in labels("decisions", decisions) %}
- {{ d }}
{% endfor %}

## 6. Other responsibilities

- Keep the AI system register complete and review the risk tier of each system at least once a year.
- Make sure each high-risk AI system has a named accountable owner, a human oversight lead and an incident response owner.
- Review the results of bias testing, monitoring and audits, and track the actions that follow to completion.
- Make sure staff receive AI literacy training suited to their role.

## 7. Conflicts of interest

A member who has a personal interest in a matter, including a role in building or buying the AI system under discussion, declares it before the item and does not take part in the decision.

## 8. Records

The secretary records attendance, decisions, the reasons for them and the actions agreed, with owners and dates. Minutes are approved at the next meeting and kept for at least six years.

## 9. Reporting

The chair reports to {{ reports_to }} at least once a year on the state of AI risk, the decisions taken and any significant incidents.

## 10. Ownership and review

This charter is owned by {{ policy_owner }} and approved by the {{ approving_body }}. It is reviewed {{ "every year" if review_cycle == "annually" else "every six months" }}.
