---
code: bias_committee_tor
version: "1.0"
title: Bias and Fairness Review Committee Terms of Reference
summary: Terms of reference for the committee that reviews bias testing and fairness results before and after an AI system is used.
catalog_codes: [GR-02]
questions:
  - {key: company_name, label: Company name, type: text, required: true, help: "The organization's name as staff know it. It appears in the title and throughout the text."}
  - {key: policy_owner, label: Policy owner, type: text, required: true, help: "Name and job title of the person who keeps this document current and answers questions about it, for example Maria Lopez, Chief AI Compliance Officer."}
  - {key: approving_body, label: Approved by, type: text, required: true, default: "AI governance committee", help: "The body or person that approves this document and any later change to it."}
  - {key: review_cycle, label: Review cycle, type: choice, default: annually, options: [{value: annually, label: Annually}, {value: six_months, label: Every six months}], help: "How often the document is reviewed. The review date is set when the document is published, and a monitoring check flags it when the date passes."}
  - {key: chair, label: Chair, type: text, required: true, default: "Chief AI Compliance Officer", help: "The role that chairs the committee."}
  - {key: members, label: Members, type: list, required: true, default: ["Head of HR", "Data Protection Officer", "General Counsel or employment counsel", "Data science lead"], help: "One role per line. Include someone who understands the statistics and someone who knows the employment or consumer law involved."}
  - {key: systems_in_scope, label: Systems in scope, type: text, required: true, default: "AI systems that make or support decisions about job applicants, employees or customers", help: "Which AI systems the committee reviews."}
  - {key: ratio_threshold, label: Impact ratio that triggers review, type: text, required: true, default: "0.80", help: "An impact ratio below this value for any group is escalated. 0.80 is the four-fifths rule of thumb; it is a screening threshold, not a legal safe harbour."}
  - {key: nyc_hiring, label: Automated hiring tools are used for New York City roles, type: yesno, default: true, help: "Tick if NYC Local Law 144 applies. Adds the annual independent bias audit and the public summary."}
---
# {{ company_name }} Bias and Fairness Review Committee Terms of Reference

## 1. Purpose

The bias and fairness review committee checks that {{ company_name }}'s AI systems do not treat people unfairly because of protected characteristics. It reviews the evidence before a system is used, after material changes, and at least once a year while the system is in use.

## 2. Scope

The committee reviews {{ systems_in_scope | lower_first }}.

## 3. Membership

The committee is chaired by the {{ chair }}. Its members are:

{% for m in members %}
- {{ m }}
{% endfor %}

## 4. What the committee reviews

- The bias testing plan for each system in scope: the groups compared, the data used and its quality, including how much of it has an unknown category.
- Selection rates or scoring rates and impact ratios for each group, and for intersectional groups where the data allows.
- Any impact ratio below {{ ratio_threshold }}, with the business owner's explanation and the proposed action.
- Complaints, appeals and human overrides that suggest unfair outcomes.

{% if nyc_hiring %}
## 5. NYC Local Law 144

For automated employment decision tools used for candidates or employees in New York City, the committee confirms before each use that:

- an independent auditor completed a bias audit no more than one year earlier, calculating selection or scoring rates and impact ratios by sex, by race and ethnicity, and for the intersectional categories, as the Department of Consumer and Worker Protection rules require (6 RCNY §5-301);
- a summary of the results, with the date of the audit and the distribution date of the tool, is published on the company website;
- candidates and employees receive notice at least 10 business days before the tool is used, and can ask for an alternative selection process or an accommodation.

The law does not set a pass mark for impact ratios. The committee decides what a result means for the company and records its reasons.

{% endif %}
## {{ "6" if nyc_hiring else "5" }}. Decisions

The committee may approve a system for use, approve it with conditions, or recommend to the AI governance committee that it is not used or is withdrawn. Every decision and its reasons are recorded.

## {{ "7" if nyc_hiring else "6" }}. Meetings and records

The committee meets before each new system in scope goes into use, after material changes, and at least twice a year. Minutes record the evidence reviewed, the decision and the actions agreed.

## {{ "8" if nyc_hiring else "7" }}. Ownership and review

These terms of reference are owned by {{ policy_owner }} and approved by the {{ approving_body }}. They are reviewed {{ "every year" if review_cycle == "annually" else "every six months" }}.
