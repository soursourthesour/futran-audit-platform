---
code: incident_response
version: "1.0"
title: AI Incident Response Procedure
summary: How AI incidents are reported, triaged, contained, notified and learned from, including EU AI Act serious incident timelines.
catalog_codes: [SD-05, GR-06]
questions:
  - {key: company_name, label: Company name, type: text, required: true, help: "The organization's name as staff know it. It appears in the title and throughout the text."}
  - {key: policy_owner, label: Policy owner, type: text, required: true, help: "Name and job title of the person who keeps this document current and answers questions about it, for example Maria Lopez, Chief AI Compliance Officer."}
  - {key: approving_body, label: Approved by, type: text, required: true, default: "AI governance committee", help: "The body or person that approves this document and any later change to it."}
  - {key: review_cycle, label: Review cycle, type: choice, default: annually, options: [{value: annually, label: Annually}, {value: six_months, label: Every six months}], help: "How often the document is reviewed. The review date is set when the document is published, and a monitoring check flags it when the date passes."}
  - {key: incident_owner, label: AI incident response owner, type: text, required: true, default: "AI incident response owner", help: "The role that leads the response to an AI incident."}
  - {key: report_route, label: How to report an incident, type: text, required: true, default: "the IT service desk, marked AI incident", help: "Where staff report a suspected AI incident."}
  - key: triage_hours
    label: Triage within
    type: choice
    default: "24"
    options: [{value: "4", label: 4 hours}, {value: "24", label: 24 hours}]
    help: "How quickly a reported incident is assessed and given a severity."
  - {key: stop_authority, label: Who can suspend a system, type: text, required: true, default: "the accountable owner of the system or the AI incident response owner", help: "Who may switch off or suspend an AI system during an incident without waiting for a committee."}
  - {key: eu_operations, label: The company operates in the EU, type: yesno, default: false, help: "Tick if any high-risk AI system is used in the EU. Adds the EU AI Act serious incident steps."}
---
# {{ company_name }} AI Incident Response Procedure

## 1. Purpose and scope

This procedure sets out how {{ company_name }} responds when an AI system causes, or nearly causes, harm. It applies to every AI system in the AI system register, whether built in-house or bought.

## 2. What counts as an AI incident

- Output that was wrong, biased or harmful and was relied on in a decision, or reached a customer, candidate or employee.
- An AI system acting outside its intended use, including an agent taking an action it was not permitted to take.
- Personal or confidential information exposed through an AI system or a prompt.
- A failure of human oversight, such as recommendations being accepted without the required review.

## 3. Reporting

Anyone who suspects an AI incident reports it at once to {{ report_route }}. The report says what happened, which system, when, who is affected and what has been done so far. Staff must not delete prompts, outputs or logs that relate to the incident.

## 4. Triage

The {{ incident_owner }} assesses each report within {{ triage_hours }} hours and gives it a severity:

- High: harm to people, a breach of law, a data breach, or a high-risk system behaving outside its intended use.
- Medium: wrong output relied on internally with limited effect, or a near miss on a high-risk system.
- Low: a minor fault with no effect on people.

## 5. Containment

{{ stop_authority | lower_first }} may suspend or switch off an AI system, or return to the manual process, while the incident is investigated. For a high-severity incident the system stays suspended until the accountable owner and the {{ incident_owner }} agree it is safe to resume.

## 6. Notification

- Personal data breaches are assessed by the Data Protection Officer. Where the GDPR applies, the supervisory authority is notified within 72 hours of becoming aware of the breach unless it is unlikely to result in a risk to people (GDPR Art. 33).
- The vendor of a bought system is told promptly and asked to investigate.
- Affected people are told what happened and what they can do, where the law requires it or fairness calls for it.
{% if eu_operations %}
- For a high-risk AI system used in the EU, when a serious incident is identified the company informs first the provider, and then the importer or distributor and the market surveillance authority (EU AI Act Art. 26(5)). Serious incidents are reported to the market surveillance authority no later than 15 days after the company becomes aware of them, 2 days for a widespread infringement or a serious disruption of critical infrastructure, and 10 days in the event of a death (EU AI Act Art. 73).
{% endif %}

## 7. Investigation and recovery

The {{ incident_owner }} finds the cause, records the evidence, agrees corrective actions with owners and dates, and confirms the fix before the system is used again. The AI system register and the system's history log are updated.

## 8. Lessons learned

High and medium incidents are reviewed by the {{ approving_body }}. The review records what happened, why, what changed and whether similar systems are affected.

## 9. Records

Incident records, the evidence and the decisions taken are kept for at least six years.

## 10. Ownership and review

This procedure is owned by {{ policy_owner }} and approved by the {{ approving_body }}. It is tested at least once a year and reviewed {{ "every year" if review_cycle == "annually" else "every six months" }}.
