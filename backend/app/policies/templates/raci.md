---
code: raci
version: "1.0"
title: RACI for AI Systems
summary: Who is responsible, accountable, consulted and informed at each step of an AI system's life, from intake to retirement.
catalog_codes: [GD-03]
questions:
  - {key: company_name, label: Company name, type: text, required: true, help: "The organization's name as staff know it. It appears in the title and throughout the text."}
  - {key: policy_owner, label: Policy owner, type: text, required: true, help: "Name and job title of the person who keeps this document current and answers questions about it, for example Maria Lopez, Chief AI Compliance Officer."}
  - {key: approving_body, label: Approved by, type: text, required: true, default: "AI governance committee", help: "The body or person that approves this document and any later change to it."}
  - {key: review_cycle, label: Review cycle, type: choice, default: annually, options: [{value: annually, label: Annually}, {value: six_months, label: Every six months}], help: "How often the document is reviewed. The review date is set when the document is published, and a monitoring check flags it when the date passes."}
  - {key: caico, label: AI compliance lead, type: text, required: true, default: "Chief AI Compliance Officer", help: "The role that runs the AI governance programme day to day."}
  - {key: system_owner, label: Accountable owner of a system, type: text, required: true, default: "Business owner of the system", help: "The role accountable for each AI system, usually the head of the department that uses it."}
  - {key: privacy, label: Privacy lead, type: text, required: true, default: "Data Protection Officer", help: "The role responsible for privacy and data protection."}
  - {key: security, label: Security lead, type: text, required: true, default: "Chief Information Security Officer", help: "The role responsible for information security."}
  - {key: legal, label: Legal, type: text, required: true, default: "General Counsel", help: "The role that gives legal advice on AI use."}
  - {key: committee, label: Governance body, type: text, required: true, default: "AI governance committee", help: "The body that approves high-risk systems and accepts residual risk."}
---
# {{ company_name }} RACI for AI Systems

## 1. Purpose

This document sets out who is Responsible (does the work), Accountable (owns the outcome and signs it off), Consulted (gives input before a decision) and Informed (is told afterwards) at each step of an AI system's life at {{ company_name }}. Each step has exactly one accountable role.

## 2. Intake and risk tiering

- Responsible: {{ system_owner }}
- Accountable: {{ caico }}
- Consulted: {{ privacy }}; {{ security }}
- Informed: {{ committee }}

## 3. Impact assessment and approval of high-risk systems

- Responsible: {{ system_owner }}
- Accountable: {{ committee }}
- Consulted: {{ caico }}; {{ privacy }}; {{ security }}; {{ legal }}
- Informed: staff who will use the system

## 4. Vendor due diligence and contract

- Responsible: procurement, with the {{ system_owner }}
- Accountable: {{ system_owner }}
- Consulted: {{ security }}; {{ privacy }}; {{ legal }}
- Informed: {{ caico }}

## 5. Bias testing and fairness review

- Responsible: the bias testing lead, or the independent auditor where the law requires one
- Accountable: {{ caico }}
- Consulted: {{ legal }}; the bias and fairness review committee
- Informed: {{ committee }}

## 6. Go-live

- Responsible: {{ system_owner }}
- Accountable: {{ system_owner }}, after the approvals above are in place
- Consulted: {{ caico }}; {{ security }}
- Informed: {{ committee }}; affected staff, candidates or customers, through the notices the law requires

## 7. Human oversight and monitoring in use

- Responsible: the human oversight lead and the named reviewers
- Accountable: {{ system_owner }}
- Consulted: {{ caico }}
- Informed: {{ committee }}, through the regular monitoring report

## 8. Incidents

- Responsible: the AI incident response owner
- Accountable: {{ system_owner }}
- Consulted: {{ security }}; {{ privacy }}; {{ legal }}
- Informed: {{ committee }}; the vendor; regulators and affected people where the law requires

## 9. Changes and retirement

- Responsible: {{ system_owner }}
- Accountable: {{ caico }} for material changes; {{ system_owner }} for other changes
- Consulted: {{ security }}; {{ privacy }}
- Informed: {{ committee }}

## 10. Ownership and review

This RACI is owned by {{ policy_owner }} and approved by the {{ approving_body }}. It is reviewed {{ "every year" if review_cycle == "annually" else "every six months" }}, and whenever roles change.
