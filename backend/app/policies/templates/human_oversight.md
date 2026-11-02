---
code: human_oversight
version: "1.0"
title: Human Oversight Procedure
summary: How named reviewers oversee AI systems that support decisions about people — competence, review steps, overrides and the authority to stop a system.
catalog_codes: [GR-05]
questions:
  - {key: company_name, label: Company name, type: text, required: true, help: "The organization's name as staff know it. It appears in the title and throughout the text."}
  - {key: policy_owner, label: Policy owner, type: text, required: true, help: "Name and job title of the person who keeps this document current and answers questions about it, for example Maria Lopez, Chief AI Compliance Officer."}
  - {key: approving_body, label: Approved by, type: text, required: true, default: "AI governance committee", help: "The body or person that approves this document and any later change to it."}
  - {key: review_cycle, label: Review cycle, type: choice, default: annually, options: [{value: annually, label: Annually}, {value: six_months, label: Every six months}], help: "How often the document is reviewed. The review date is set when the document is published, and a monitoring check flags it when the date passes."}
  - {key: oversight_lead, label: Human oversight lead, type: text, required: true, default: "Human oversight lead", help: "The role that designs and monitors human review of AI outputs."}
  - {key: systems, label: Systems covered, type: text, required: true, default: "every Tier 3 AI system and every AI system that supports decisions about people", help: "Which AI systems this procedure applies to."}
  - {key: sample_rate, label: Quality check on reviews, type: text, required: true, default: "5% of reviewed decisions each month", help: "How many reviewed decisions the oversight lead re-checks to confirm the reviews are real."}
  - {key: stop_authority, label: Who can stop a system, type: text, required: true, default: "any named reviewer, the human oversight lead or the accountable owner", help: "Who may stop the system or switch to the manual process when something looks wrong."}
  - {key: eu_operations, label: High-risk AI is used in the EU, type: yesno, default: false, help: "Tick if any system covered is a high-risk system used in the EU. Adds the EU AI Act references."}
---
# {{ company_name }} Human Oversight Procedure

## 1. Purpose and scope

This procedure makes sure that people, not AI systems, remain responsible for decisions at {{ company_name }}. It applies to {{ systems }}.

## 2. Named reviewers

- Each system covered has named reviewers, recorded in the AI system register.
- A reviewer has the competence, training and authority to question and override the system's output{% if eu_operations %} (EU AI Act Art. 26(2)){% endif %}.
- Reviewers complete the human oversight training before they start and every year after that.

## 3. What a reviewer does

1. Looks at the information the system used and its output before acting on it.
2. Checks the output against their own judgement and the other information available, and does not accept it only because the system produced it.
3. Overrides the output when it is wrong or unfair, and records the reason.
4. Escalates to the {{ oversight_lead }} when the system seems to behave outside its intended use.

## 4. Automation bias

People tend to rely too much on automated recommendations, especially under time pressure. Workloads are set so reviewers have time to review properly, and the {{ oversight_lead }} watches for signs that outputs are being accepted without real review, such as an override rate close to zero{% if eu_operations %} (EU AI Act Art. 14(4)(b)){% endif %}.

## 5. Stopping a system

{{ stop_authority | capitalize }} may stop the system or switch to the manual process when its output looks wrong or harmful{% if eu_operations %} (EU AI Act Art. 14(4)(e)){% endif %}. They then report it under the AI incident response procedure.

## 6. Checking that oversight works

- The {{ oversight_lead }} re-checks {{ sample_rate }} and records the result.
- The override rate and its trend are reported to the {{ approving_body }} every quarter.
- Findings lead to more training, changes to the system or a review of its use.

## 7. Records

Reviews, overrides and their reasons are kept for at least as long as the system's logs{% if eu_operations %}, and in any case for at least six months (EU AI Act Art. 26(6)){% endif %}.

## 8. Ownership and review

This procedure is owned by {{ policy_owner }} and approved by the {{ approving_body }}. It is reviewed {{ "every year" if review_cycle == "annually" else "every six months" }}.
