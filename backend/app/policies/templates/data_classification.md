---
code: data_classification
version: "1.0"
title: Data Classification for AI
summary: Which classes of information may be used with which AI tools, and how prompts, outputs and training data are handled.
catalog_codes: [SD-02]
questions:
  - {key: company_name, label: Company name, type: text, required: true, help: "The organization's name as staff know it. It appears in the title and throughout the text."}
  - {key: policy_owner, label: Policy owner, type: text, required: true, help: "Name and job title of the person who keeps this document current and answers questions about it, for example Maria Lopez, Chief AI Compliance Officer."}
  - {key: approving_body, label: Approved by, type: text, required: true, default: "AI governance committee", help: "The body or person that approves this document and any later change to it."}
  - {key: review_cycle, label: Review cycle, type: choice, default: annually, options: [{value: annually, label: Annually}, {value: six_months, label: Every six months}], help: "How often the document is reviewed. The review date is set when the document is published, and a monitoring check flags it when the date passes."}
  - {key: enterprise_tools, label: AI tools approved for confidential information, type: list, required: true, default: ["Microsoft Copilot (company account)"], help: "One per line. Tools under a company contract that keeps data inside the company and does not use it for training."}
  - {key: restricted_examples, label: Examples of restricted information, type: list, required: true, default: ["Health information", "Government identification numbers", "Bank and payment card details", "Passwords, keys and credentials"], help: "One per line. The most sensitive information the company holds."}
  - key: prompt_retention
    label: Keep prompts and outputs of company tools for
    type: choice
    default: "12"
    options: [{value: "6", label: 6 months}, {value: "12", label: 12 months}, {value: "24", label: 24 months}]
    help: "How long logs of prompts and outputs in company AI tools are kept, so incidents can be investigated. High-risk systems used in the EU must keep their logs for at least six months."
---
# {{ company_name }} Data Classification for AI

## 1. Purpose

This document applies {{ company_name }}'s information classes to the use of AI. It tells staff which information may be used with which AI tools, and how prompts, outputs and training data are handled.

## 2. Information classes and AI

- Public: information already published by the company. May be used with any approved AI tool.
- Internal: information for staff only, such as internal procedures. May be used with approved AI tools under a company account.
- Confidential: client, customer, employee and commercial information. May be used only with the tools listed in section 3, and only for the purpose it was collected for.
- Restricted: the most sensitive information. Must not be entered into any AI tool unless the {{ approving_body }} has approved that tool and that use in writing.

Examples of restricted information:

{% for e in restricted_examples %}
- {{ e }}
{% endfor %}

## 3. Tools approved for confidential information

{% for t in enterprise_tools %}
- {{ t }}
{% endfor %}

## 4. Prompts and outputs

- An output takes the highest class of the information used to produce it.
- Prompts and outputs in company AI tools are kept for {{ prompt_retention }} months and then deleted, unless they are needed for an investigation or a legal hold.
- Outputs containing personal data are handled under the company's privacy policy like any other personal data.

## 5. Training and fine-tuning data

- Personal or confidential information is used to train or fine-tune a model only after the Data Protection Officer has approved the purpose, the legal basis and the safeguards.
- Training data is documented: its source, what it contains, how it was checked for quality and gaps, and how long it is kept.

## 6. Ownership and review

This document is owned by {{ policy_owner }} and approved by the {{ approving_body }}. It is reviewed {{ "every year" if review_cycle == "annually" else "every six months" }}.
