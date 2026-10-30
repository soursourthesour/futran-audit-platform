/* Help text for the regulatory master (M1–M5) and the intro letter. */

export const libraryHelp = {
  search: 'Searches law names, citations, geographies and requirement text.',
  region: 'Where the law applies. Frameworks such as NIST AI RMF are voluntary and used as the audit baseline.',
  status: 'Status of the approved version. A proposed change does not alter it until the Chief Auditor approves.',
  appliesTo: 'Who carries the duties: a deployer uses AI, a developer or provider builds it, an employer uses it on staff, a data fiduciary decides how personal data is used.',
  topic: 'Subject tags used for filtering and for alert rules.',
  show: 'The library lists laws with statutory requirements. Show all laws to include every row of the imported law matrix.',
};

export const bulkHelp = {
  reviewer: 'The Futran person who checks these laws at the next review.',
  reviewDate: 'When the laws are next due for review. Applies straight away; it does not change law content.',
  frequency: 'How often the refresh checks these laws. Weekly suits a legislature in session.',
  watch: 'Watch-list laws are flagged on the dashboard and in every refresh.',
  topics: 'Adds a topic to every selected law. This is a content change and goes to the review queue.',
  appliesTo: 'Adds a party the selected laws apply to. This is a content change and goes to the review queue.',
  roleLevel: 'Sets this role on every selected law once approved. The role catalogue (M4) and every client system under these laws follow.',
  neededBy: 'The stage by which the role must be filled.',
  reason: 'Saved with each proposed change and in each law version history.',
};

export const lawHelp = {
  sourceName: "The name of the page as its publisher titles it, for example “NYC Admin. Code § 20-870” or “DCWP final rule”.",
  sourceKind: "Official: the legislature, regulator or official journal. Secondary: a law firm alert or commentary, useful for context but never the basis of a requirement.",
  draftRef: 'Paste the bill number or the official legislature or regulator link. Claude reads the official text and fills the form; nothing is saved until you send it for approval.',
  region: 'The group the law is listed under in the library.',
  geography: 'The jurisdiction code, for example US-CO, US-NYC, EU or IN.',
  shortName: 'The name auditors use, for example Colorado AI Act.',
  label: 'A short column heading for the role matrix and letters, for example Colorado. Leave blank to use the short name.',
  citation: 'The bill or instrument number, for example SB 26-189 or Regulation (EU) 2024/1689.',
  type: 'Statute, regulation, executive order, guidance, framework or a pending bill.',
  binding: 'Voluntary frameworks and guidance are not binding; they are shown as recommended.',
  topics: 'Subject tags used for filtering and alert rules.',
  status: 'Enacted but not yet in force, in force, phased, delayed, guidance or repealed.',
  signed: 'The date the law was signed or adopted.',
  effective: 'The date the law takes effect.',
  compliance: 'The date organizations must comply. Drives the "effective in the next 90 days" count.',
  enforcer: 'Who enforces the law, for example the State Attorney General.',
  pra: 'Whether individuals can sue under the law.',
  penalty: 'Amount and basis, for example per violation or per day.',
  cure: 'Time allowed to fix a violation after notice, and any end date.',
  appliesTo: 'Who carries the duties under the law.',
  scope: 'Who the law covers, which decisions, and any size or revenue threshold. Shown to clients in the intro letter.',
  exemptions: 'Who is excluded, for example employers with fewer than 50 staff.',
  sourceUrl: 'An official source (legislature, regulator or official journal) where possible. Law firm alerts are marked secondary.',
  question: 'Asked in the client applicability check (M5). A decisive question that is answered no takes the law out of scope.',
  prefill: 'Where the answer comes from before anyone answers it: client geographies or the decision impact of the client\'s AI use.',
};

export const requirementHelp = {
  suggestField: "The part of the law record your suggestion is about. The Chief Auditor sees it next to the current text and your source.",
  text: 'The duty in plain words, as an auditor would test it.',
  appliesTo: 'Who carries this duty under the law.',
  neededBy: 'The stage by which the client must meet it.',
  role: 'The catalogue role that is responsible. Adds the role to the law\'s role map.',
  aiTypes: 'Which kinds of AI the rule appears under in the intro letter.',
  evidence: 'What the auditor asks to see to confirm the duty is met.',
  citation: 'Section number, for example §20-871(a)(1). Every requirement needs one.',
  quote: 'The exact words of the law the requirement relies on. Every requirement needs one.',
  sourceUrl: 'The page the quote comes from.',
  reason: 'Why the change is needed. Saved with the proposed change.',
  suggestSource: 'Auditor suggestions need the source link and the quoted passage.',
};

export const roleHelp = {
  name: 'The role name clients see in the register and the intro letter.',
  level: 'Company roles are filled once for the whole client; system roles for each AI system; agent roles for each AI agent.',
  stage: 'The stage by which the role must be filled when no law sets an earlier one.',
  checks: 'Extra confirmations recorded when the role is assigned, such as training and authority to override for human oversight.',
  description: 'The responsibility, as shown in the intro letter.',
  lawLevel: 'Required by the law, recommended, or not required. Changes go to the Chief Auditor as proposed changes.',
  lawStage: 'The stage this law needs the role by.',
  reason: 'Saved with each proposed change.',
  show: 'Choose which laws appear as columns.',
};

export const applicabilityHelp = {
  geoSearch: "Type at least two letters of a country, state or city. The list below shows the geographies in the law library that match.",
  scopeMode: "From the scope questions: the platform decides from the client's answers to the law's scope tests. Set by hand: you record the decision yourself, with a reason, for example on counsel's advice.",
  inScope: "Your decision on whether this law applies to the client. It overrides the scope questions and is recorded in the audit log with your reason.",
  geography: 'A country, state or city where the client operates or has people, customers or data.',
  basis: 'Why the geography counts: an office, employees, candidates, customers or personal data.',
  answer: 'Your answer replaces the pre-filled one. Clear it to go back to the pre-filled answer.',
  overrideReason: 'Why the law is in or out of scope regardless of the questions. Shown as the reason.',
  opening: 'Replaces the opening paragraph of the letter.',
  closing: 'An extra paragraph after section 5, for example a note from the Chief Auditor.',
};
