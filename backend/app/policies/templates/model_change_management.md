---
code: model_change_management
version: "1.0"
title: Model Change Management Procedure
summary: How changes to AI models, prompts, data and vendors are classified, tested, approved, recorded and rolled back.
catalog_codes: []
questions:
  - {key: company_name, label: Company name, type: text, required: true, help: "The organization's name as staff know it. It appears in the title and throughout the text."}
  - {key: policy_owner, label: Policy owner, type: text, required: true, help: "Name and job title of the person who keeps this document current and answers questions about it, for example Maria Lopez, Chief AI Compliance Officer."}
  - {key: approving_body, label: Approved by, type: text, required: true, default: "AI governance committee", help: "The body or person that approves this document and any later change to it."}
  - {key: review_cycle, label: Review cycle, type: choice, default: annually, options: [{value: annually, label: Annually}, {value: six_months, label: Every six months}], help: "How often the document is reviewed. The review date is set when the document is published, and a monitoring check flags it when the date passes."}
  - {key: change_approver, label: Who approves material changes, type: text, required: true, default: "the Chief AI Compliance Officer", help: "Who must approve a material change before it goes into use."}
  - {key: test_set, label: Minimum tests before release, type: list, required: true, default: ["Accuracy against the agreed test set", "Bias testing across the groups the system affects", "Security testing, including prompt injection for generative AI"], help: "One per line. The tests every significant or material change must pass."}
  - {key: vendor_notice, label: Vendors must give notice of model changes, type: text, required: true, default: "30 days", help: "The notice you require from vendors before they change the model behind a product you use."}
  - {key: eu_operations, label: High-risk AI is used in the EU, type: yesno, default: false, help: "Tick if any system is a high-risk system used in the EU. Adds the log retention point."}
---
# {{ company_name }} Model Change Management Procedure

## 1. Purpose and scope

This procedure controls changes to AI systems at {{ company_name }}: the model or its version, the prompts and instructions, the data it uses, its integrations and permissions, and the vendor behind it. It applies to systems built in-house and to bought systems where the company can see or control the change.

## 2. Types of change

- Minor: no effect on outputs, such as a fix to the user interface. Recorded in the system's history log.
- Significant: may change outputs, such as a new model version, new prompts or new data sources. Tested and approved by the accountable owner.
- Material: changes what the system is used for, who it affects, the decisions it supports, its risk tier or the places it is used. Re-assessed and approved by {{ change_approver }} before use.

## 3. Before a significant or material change

1. Record the change, the reason and the expected effect in the AI system register.
2. Run the minimum tests:
{% for t in test_set %}
- {{ t }}
{% endfor %}

3. Compare the results with the current version and record any difference in outcomes for groups of people.
4. Agree a rollback plan: how to return to the previous version and who decides.
5. Update the instructions for named reviewers if their work changes.

## 4. Approval and release

A change goes into use only after the approval its type requires. Material changes to a system that supports decisions about people also go to the bias and fairness review committee. Staff who use the system are told what changed.

## 5. Vendor changes

Vendors must give {{ vendor_notice }} notice before changing the model behind a product the company uses. The accountable owner assesses the change under this procedure and may pause use until testing is complete.

## 6. After release

The accountable owner watches the system closely for the first weeks after a change and rolls back if outcomes move outside the agreed range.

## 7. Records

The register keeps the version history, test results, approvals and rollback decisions for each system{% if eu_operations %}, and automatically generated logs of high-risk systems are kept for at least six months (EU AI Act Art. 26(6)){% endif %}.

## 8. Ownership and review

This procedure is owned by {{ policy_owner }} and approved by the {{ approving_body }}. It is reviewed {{ "every year" if review_cycle == "annually" else "every six months" }}.
