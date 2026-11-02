"""Glossary for the client Q&A helper (spec §2 and the template's Appendix C terms). Plain definitions written for
people at the client who answer the questionnaire."""
import re

TERMS: list[tuple[str, str, str]] = [
    ("AI system", r"\bai system", "Software that uses a model trained on data to make predictions, recommendations, content or decisions. One system can serve several business uses."),
    ("Use case", r"use case", "One business use of AI, for example screening job applications. The inventory records each one separately."),
    ("Model card", r"model card|model documentation", "A short document that describes what a model is for, the data it was trained on, how well it performs, and its known limitations."),
    ("Training data", r"training|validation / test|test split", "The data used to build the model. Validation and test data are held back to check how well it works."),
    ("Bias testing", r"bias|fairness|disparate", "Checking whether the system's outcomes differ for groups of people, such as by sex or race/ethnicity, in a way that is not justified."),
    ("Impact ratio", r"impact ratio|disparate impact", "The selection rate of one group divided by the rate of the most-selected group. Below 0.80 is a common warning sign (the four-fifths rule)."),
    ("Protected attribute", r"protected attribute", "A characteristic the law protects from discrimination, such as sex, race, ethnicity, age or disability."),
    ("Human oversight", r"human|override|reviewer|in-the-loop", "A person who reviews the system's output and can change or stop the outcome before it takes effect."),
    ("Explainability", r"explainab|interpretab|shap|lime", "The ability to say, in terms a person understands, why the system produced a particular output."),
    ("Model drift", r"drift", "A change in how well a model performs over time, usually because the data it sees in use differs from the data it was trained on."),
    ("Monitoring", r"monitor", "Regular checks, automated or manual, that the system keeps working as intended once it is in use."),
    ("Reproducibility", r"reproducib", "Being able to rebuild the same model from the same data and code and get the same results."),
    ("Change management", r"change management|change control|retraining", "The process for approving, testing and recording changes to a model before they go live."),
    ("Incident", r"incident", "An event where the AI system caused, or nearly caused, harm, an error or a breach of policy or law."),
    ("Vendor assurance", r"vendor|third[- ]party|supplier", "Evidence from a supplier that its AI product is built and run responsibly, such as audit reports, test results or contract terms."),
    ("Data classification", r"classif|sensitive|personal data|confidential", "Labelling data by how sensitive it is (for example public, internal, confidential, personal) so it is handled correctly."),
    ("Legal basis", r"legal basis|consent|lawful", "The reason the law allows personal data to be used, such as consent, a contract or a legitimate interest."),
    ("AEDT", r"aedt|automated employment", "Automated employment decision tool: software that substantially assists decisions about hiring or promotion (NYC Local Law 144)."),
    ("Null-compliance risk", r"null|sufficien", "When a process is followed on paper but has no real substance, for example a bias audit run without demographic data."),
    ("Risk tier", r"tier", "Futran's rating of how much harm a use of AI could do: 1 baseline, 2 elevated, 3 high-risk."),
    ("Source person", r"source person|who gave", "The person who gave an answer, recorded by name and job title so the auditor can follow up."),
]


def terms_for(*texts: str) -> list[dict]:
    blob = " ".join(t or "" for t in texts).lower()
    return [{"term": t, "meaning": m} for t, pat, m in TERMS if re.search(pat, blob, re.I)]
