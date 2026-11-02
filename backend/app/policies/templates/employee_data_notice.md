---
code: employee_data_notice
version: "1.0"
title: Employee AI Data Notice
summary: Tells employees and candidates which AI tools use their information, why, what decisions they support and what rights they have.
catalog_codes: []
questions:
  - {key: company_name, label: Company name, type: text, required: true, help: "The organization's name as staff know it. It appears in the title and throughout the text."}
  - {key: policy_owner, label: Policy owner, type: text, required: true, help: "Name and job title of the person who keeps this document current and answers questions about it, for example Maria Lopez, Chief AI Compliance Officer."}
  - {key: approving_body, label: Approved by, type: text, required: true, default: "AI governance committee", help: "The body or person that approves this document and any later change to it."}
  - {key: review_cycle, label: Review cycle, type: choice, default: annually, options: [{value: annually, label: Annually}, {value: six_months, label: Every six months}], help: "How often the document is reviewed. The review date is set when the document is published, and a monitoring check flags it when the date passes."}
  - {key: tools, label: AI tools that use employee or candidate information, type: list, required: true, default: ["Résumé screening in the applicant tracking system", "Microsoft Copilot (company account)"], help: "One per line. Include tools that analyse or make recommendations about employees or candidates."}
  - {key: purposes, label: What the tools are used for, type: list, required: true, default: ["Ranking job applications before a recruiter reviews them", "Drafting and summarising documents"], help: "One per line, in plain words."}
  - {key: contact, label: Contact for questions and requests, type: text, required: true, default: "the HR team", help: "Who people contact to ask a question, ask for human review or correct their data."}
  - {key: nyc_hiring, label: Automated hiring tools are used for New York City roles, type: yesno, default: false, help: "Tick if NYC Local Law 144 applies. Adds the notice of an automated employment decision tool and the right to ask for an alternative process."}
  - {key: illinois, label: Employees or candidates in Illinois, type: yesno, default: false, help: "Tick if AI is used in employment decisions about people in Illinois. Adds the notice the Illinois Human Rights Act requires."}
  - {key: eu_operations, label: Employees in the EU, type: yesno, default: false, help: "Tick if employees in the EU are affected. Adds GDPR rights and the EU AI Act duty to inform workers."}
---
# {{ company_name }} Employee AI Data Notice

## 1. Why you are receiving this notice

{{ company_name }} uses artificial intelligence (AI) tools in some of its work. Some of these tools use information about employees and job candidates. This notice explains which tools, what they are used for, and what you can do if you have questions or concerns.

## 2. The AI tools that use your information

{% for t in tools %}
- {{ t }}
{% endfor %}

## 3. What they are used for

{% for p in purposes %}
- {{ p }}
{% endfor %}

## 4. How decisions are made

AI tools support people at {{ company_name }}; they do not make decisions about hiring, pay, promotion, discipline or dismissal on their own. A trained person reviews each recommendation and can override it.

{% if nyc_hiring %}
## 5. Notice of an automated employment decision tool (New York City)

For roles in New York City, {{ company_name }} uses an automated employment decision tool in assessing candidates or employees. We tell you at least 10 business days before it is used, and we tell you the job qualifications and characteristics it assesses. You may ask for an alternative selection process or an accommodation by contacting {{ contact }}. A summary of the most recent bias audit of the tool is published on our website (NYC Local Law 144 of 2021).

{% endif %}
{% if illinois %}
## {{ "6" if nyc_hiring else "5" }}. Notice for Illinois

Where AI is used in recruitment, hiring, promotion, training, discipline, discharge or other terms of employment for people in Illinois, {{ company_name }} gives notice of that use, as the Illinois Human Rights Act requires (775 ILCS 5/2-102(L)). The company does not use AI in a way that discriminates on the basis of a protected class, and does not use zip codes as a proxy for a protected class.

{% endif %}
## {{ 5 + (1 if nyc_hiring else 0) + (1 if illinois else 0) }}. Your rights

- Ask how an AI-assisted decision about you was made, and ask for a person to review it.
- Ask to see and correct the information about you that the tools use.
{% if eu_operations %}
- If you are in the EU, you also have the rights given by the GDPR, including the right not to be subject to a decision based solely on automated processing that significantly affects you, and to obtain human intervention and contest the decision (GDPR Art. 22). Before a high-risk AI system is put into use at work, the company informs workers' representatives and the workers affected (EU AI Act Art. 26(7)).
{% endif %}

To use any of these rights, contact {{ contact }}.

## {{ 6 + (1 if nyc_hiring else 0) + (1 if illinois else 0) }}. Ownership and review

This notice is owned by {{ policy_owner }} and approved by the {{ approving_body }}. It is reviewed {{ "every year" if review_cycle == "annually" else "every six months" }}, and updated when a new AI tool starts to use employee or candidate information.
