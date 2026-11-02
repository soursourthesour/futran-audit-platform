---
code: acceptable_use
version: "1.0"
title: AI Acceptable Use Policy
summary: Rules for staff use of AI tools — approved tools, information that must never be entered, decisions about people and how to report problems.
catalog_codes: [GD-04]
questions:
  - {key: company_name, label: Company name, type: text, required: true, help: "The organization's name as staff know it. It appears in the title and throughout the text."}
  - {key: policy_owner, label: Policy owner, type: text, required: true, help: "Name and job title of the person who keeps this document current and answers questions about it, for example Maria Lopez, Chief AI Compliance Officer."}
  - {key: approving_body, label: Approved by, type: text, required: true, default: "AI governance committee", help: "The body or person that approves this document and any later change to it."}
  - {key: review_cycle, label: Review cycle, type: choice, default: annually, options: [{value: annually, label: Annually}, {value: six_months, label: Every six months}], help: "How often the document is reviewed. The review date is set when the document is published, and a monitoring check flags it when the date passes."}
  - {key: approved_tools, label: Approved AI tools, type: list, required: true, help: "One tool per line, with the account type where it matters, for example Microsoft Copilot (company account). Only these tools may be used for company work."}
  - key: personal_accounts
    label: Personal AI accounts for work
    type: choice
    default: not_allowed
    options: [{value: not_allowed, label: Not allowed}, {value: public_only, label: Allowed for public information only}]
    help: "Whether staff may use their own or free AI accounts for company work. Free consumer accounts may keep what is typed and use it to train models."
  - key: prohibited_data
    label: Never enter into any AI tool
    type: multi
    required: true
    default: [client_data, personal_data, source_code]
    options:
      - {value: client_data, label: Client or customer data}
      - {value: personal_data, label: Applicant and employee personal data}
      - {value: source_code, label: Source code and credentials}
      - {value: health, label: Health information}
      - {value: financial, label: Non-public financial information}
      - {value: confidential, label: Information marked confidential or restricted}
    help: "Categories of information staff must not enter into any AI tool unless the approving body has cleared that tool for that information in writing."
  - {key: request_route, label: How to ask for a new tool, type: text, required: true, default: "the AI governance committee, through the IT service desk", help: "Who staff contact to have a new AI tool reviewed and approved."}
  - {key: incident_contact, label: Who to report problems to, type: text, required: true, default: "their manager and the AI incident response owner", help: "Who staff tell when an AI tool gets something wrong or information goes where it should not."}
  - {key: contractors, label: Policy also covers contractors and temporary workers, type: yesno, default: true, help: "Tick if contractors, agency and temporary workers who use company systems must follow this policy."}
  - {key: people_decisions, label: AI is used in decisions about people, type: yesno, default: true, help: "Tick if any AI tool is used in hiring, promotion, performance, credit or similar decisions. Adds the human review rule."}
  - {key: nyc_hiring, label: Automated hiring tools are used for New York City roles, type: yesno, default: false, help: "Tick if an automated employment decision tool is used for candidates or employees in New York City. Adds the NYC Local Law 144 conditions."}
  - {key: eu_operations, label: The company operates in the EU, type: yesno, default: false, help: "Tick if AI is used in the EU or its output is used there. Adds the EU AI Act points on AI literacy and prohibited practices."}
---
# {{ company_name }} AI Acceptable Use Policy

## 1. Purpose and scope

This policy sets the rules for how {{ company_name }} staff{% if contractors %}, contractors and temporary workers{% endif %} use artificial intelligence (AI) tools in their work, in all locations and departments. It covers general-purpose assistants such as chat tools, AI features built into other software, AI agents that take actions, and AI systems the company builds or buys.

## 2. Approved tools

Staff may use only the following AI tools for {{ company_name }} work:

{% for tool in approved_tools %}
- {{ tool }}
{% endfor %}

{% if personal_accounts == "not_allowed" %}
Use of personal or free AI accounts for {{ company_name }} work is not allowed.
{% else %}
Personal or free AI accounts may be used for {{ company_name }} work only with information that is already public. No other company information may be entered into them.
{% endif %}

To ask for a new tool, contact {{ request_route }}. A tool is approved only after its data handling, security and terms of use have been reviewed and it has been added to the AI system register.

## 3. Information you must never enter

Never enter the following into any AI tool, including the approved tools above, unless the {{ approving_body }} has approved that tool for that information in writing:

{% for item in labels("prohibited_data", prohibited_data) %}
- {{ item }}
{% endfor %}

If you are unsure whether information may be entered, treat it as if it may not and ask first.

{% if people_decisions %}
## 4. Decisions about people

No AI output may be the sole basis for a decision to hire, promote, discipline or dismiss a person, or for any other decision with a significant effect on someone. A trained person reviews every AI recommendation, can override it, and records the reason when they do.

{% if nyc_hiring %}
An automated employment decision tool is used for candidates or employees in New York City only when it has had a bias audit within the past year, a summary of the results is published on the company website, and candidates and employees have been told at least 10 business days before it is used (NYC Local Law 144 of 2021).

{% endif %}
{% endif %}
## {{ "5" if people_decisions else "4" }}. Using AI output responsibly

- You are responsible for work you produce with AI help. Check facts, figures, citations and code before you rely on them or share them.
- Say that content was generated with AI where the law, a contract or the reader's reasonable expectation requires it.
- Do not use AI to create content that is discriminatory, harassing or misleading, or that imitates a real person without their consent.
- Do not connect an AI tool or agent to company email, files or systems unless that connection has been approved.

## {{ "6" if people_decisions else "5" }}. Uses that are not allowed

- Any use that breaks the law or another {{ company_name }} policy.
- Monitoring staff with AI beyond what the law and the company's employee monitoring notices allow.
{% if eu_operations %}
- The practices prohibited by Article 5 of the EU AI Act, including manipulative techniques that cause harm, social scoring, and inferring the emotions of people at work or in education other than for medical or safety reasons.
{% endif %}
- Using AI to make a decision about a person without the human review described in this policy.

## {{ "7" if people_decisions else "6" }}. Training

Everyone who uses AI tools for {{ company_name }} work completes the company's AI literacy training when they start using AI tools and again every year.{% if eu_operations %} This supports the company's duty under Article 4 of the EU AI Act, as amended by Regulation (EU) 2026/1744, to take measures to support the AI literacy of staff and others who operate or use AI systems on its behalf.{% endif %}


## {{ "8" if people_decisions else "7" }}. Reporting problems

Tell {{ incident_contact }} straight away if:

- an AI tool produced harmful, biased or clearly wrong output that someone relied on;
- information was entered into a tool that was not approved for it;
- you suspect an AI tool is being misused.

Reports made in good faith are never held against the person who makes them.

## {{ "9" if people_decisions else "8" }}. Breaches

A breach of this policy may lead to loss of access to AI tools and to disciplinary action under the company's disciplinary procedure.

## {{ "10" if people_decisions else "9" }}. Ownership and review

This policy is owned by {{ policy_owner }} and approved by the {{ approving_body }}. It is reviewed {{ "every year" if review_cycle == "annually" else "every six months" }}, and sooner when the company adopts a significant new AI tool or a law that applies to it changes.
