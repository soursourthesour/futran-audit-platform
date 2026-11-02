---
code: vendor_due_diligence
version: "1.0"
title: AI Vendor Due Diligence Questionnaire
summary: Questions to send an AI vendor before purchase or renewal, covering data use, security, testing, transparency and contract terms.
catalog_codes: [SD-04]
questions:
  - {key: company_name, label: Company name, type: text, required: true, help: "The organization's name as staff know it. It appears in the title and throughout the text."}
  - {key: policy_owner, label: Policy owner, type: text, required: true, help: "Name and job title of the person who keeps this document current and answers questions about it, for example Maria Lopez, Chief AI Compliance Officer."}
  - {key: approving_body, label: Approved by, type: text, required: true, default: "AI governance committee", help: "The body or person that approves this document and any later change to it."}
  - {key: review_cycle, label: Review cycle, type: choice, default: annually, options: [{value: annually, label: Annually}, {value: six_months, label: Every six months}], help: "How often the document is reviewed. The review date is set when the document is published, and a monitoring check flags it when the date passes."}
  - {key: review_owner, label: Who reviews the answers, type: text, required: true, default: "the Chief AI Compliance Officer, with the Chief Information Security Officer", help: "Who assesses the vendor's answers and recommends approval."}
  - {key: notify_hours, label: Vendor must report incidents within, type: text, required: true, default: "72 hours", help: "The incident notification period you will ask for in the contract."}
  - {key: hiring_tools, label: Include questions for hiring and HR tools, type: yesno, default: false, help: "Tick for tools used in recruitment or employment decisions. Adds questions on bias audits and NYC Local Law 144."}
  - {key: eu_operations, label: Include EU AI Act questions, type: yesno, default: false, help: "Tick if the tool will be used in the EU. Adds questions on the provider's EU AI Act obligations."}
---
# {{ company_name }} AI Vendor Due Diligence Questionnaire

## How this questionnaire is used

{{ company_name }} sends this questionnaire to vendors of AI tools before purchase and at each renewal. Answers are reviewed by {{ review_owner }}. Please answer every question; where a question does not apply, say why. Attach evidence where it is asked for.

## 1. The product and the model

1. Describe what the product does and which features use AI.
2. Which models does the product use, who provides them, and where are they hosted?
3. How do you tell customers about significant changes to the model or its behaviour, and how much notice do you give?

## 2. Our data

1. What data of ours does the product collect, including prompts, files and outputs?
2. Is any of our data used to train or improve your models or anyone else's? If it can be switched off, how?
3. Where is our data stored and processed, and how long is it kept? Can we have it deleted on request?
4. List the sub-processors that handle our data and where they are located.

## 3. Security

1. Provide your most recent SOC 2 Type II report or ISO/IEC 27001 certificate, with its period and scope.
2. Do you hold ISO/IEC 42001 certification for your AI management system, or plan to?
3. How do you protect the product against prompt injection, data leakage between customers and misuse?

## 4. Testing and accuracy

1. How do you test the product for accuracy, reliability and harmful output before release and afterwards?
2. Do you test for bias across groups of people? Provide the most recent results and the method used.
3. What are the known limitations of the product, and where are they documented for users?

{% if hiring_tools %}
## 5. Hiring and employment tools

1. Has the tool had a bias audit by an independent auditor that meets NYC Local Law 144 and the DCWP rules? Provide the summary of results and the audit date.
2. Which job qualifications and characteristics does the tool assess, and what data does it use?
3. Can the tool support an alternative selection process or accommodation for a candidate who asks for one?

{% endif %}
{% if eu_operations %}
## {{ "6" if hiring_tools else "5" }}. EU AI Act

1. Is the product, or any use we intend, a high-risk AI system under Annex III of the EU AI Act? If so, has it completed the conformity assessment and been registered?
2. Provide the instructions for use, including the information deployers need to carry out human oversight and keep logs.
3. How will you inform us of serious incidents and corrective actions?

{% endif %}
## {{ (5 + (1 if hiring_tools else 0) + (1 if eu_operations else 0)) }}. Transparency and oversight

1. Can a user see why the product produced a particular output, and can a person override it?
2. What logs does the product keep of inputs, outputs and user actions, and can we export them?

## {{ (6 + (1 if hiring_tools else 0) + (1 if eu_operations else 0)) }}. Incidents and contract terms

1. Will you notify us of any security or AI incident affecting our data or our use of the product within {{ notify_hours }}?
2. Will you accept contract terms that prohibit training on our data, set data residency, give us audit rights and require deletion at the end of the contract?
3. What liability do you accept for errors in the product's output?

## Ownership and review

This questionnaire is owned by {{ policy_owner }} and approved by the {{ approving_body }}. It is reviewed {{ "every year" if review_cycle == "annually" else "every six months" }}.
