/* Help for the AI features (spec §21 F1, F5, F10). */

export const aiSwitchHelp = {
  enabled: 'When on, the auditors on this engagement can use the copilot and the client can use "Explain this question". Every output is a suggestion a named person accepts or rejects, and every use is logged.',
  consent: 'Where the client agreed to AI-assisted review, for example "Engagement letter clause 9.2, signed 14 March". Required to turn AI on.',
};

export const copilotHelp = {
  documents: 'The copilot reads only the documents uploaded to this engagement as evidence or governance documents. It does not search the web.',
  editValue: 'Change the suggested answer before accepting it. The edit is recorded against the suggestion.',
  editDetail: 'Context for the answer. The citation is added after it automatically.',
  reject: 'Why the suggestion is wrong or not useful. Kept in the AI interaction log.',
  ask: 'Ask about the documents uploaded to this engagement. The answer cites the passages it relies on; an answer with no passage is marked unsupported.',
  evidenceDescription: "What the client should provide. The client sees this text as written.",
  evidenceDue: 'The client is reminded 3 days before this date.',
  signoff: 'Sign-off 5 approves the final tiers and findings; sign-off 7 the final report. Run the review before each.',
  summaryKind: 'An engagement summary covers this audit; a client summary is written for the client as a whole.',
  summaryEdit: 'Edit the text before using it. It replaces the overall narrative in the executive summary.',
  useInReport: 'Writes the accepted text into the report as the overall assessment narrative. Possible until the client draft is released.',
  replaceNarrative: 'Leave this unticked to keep a narrative someone has already written; accepting then stops and says so. The replaced text is kept in the audit log.',
  checklist: 'The checklist whose linked evidence the copilot reads.',
};

export const obligationHelp = {
  text: 'The duty in one sentence, as it should appear on the law record.',
  actor: 'Who carries the duty under this law.',
  action: 'What the actor must do.',
  condition: 'When the duty applies, if only in some cases.',
  deadline: 'By when, for example "no less than 10 business days before use".',
  citation: 'The section of the law, for example "§20-871(b)(1)".',
  questions: 'Template question codes this obligation is tested by, separated by commas, for example "7.2.01, 6.2.01".',
  reject: 'Why this is not an obligation of the law. Kept with the record.',
};

export const questionnaireHelp = {
  confirmAudited: 'Tick only after checking that the quoted passage from your signed Futran report supports everything the answer says. Without your confirmation the label is left off the answer, the export and the answer library.',
  file: 'The questionnaire your customer sent, as an Excel workbook (XLSX), Word document (DOCX) or PDF. Questions are found automatically.',
  customer: 'The customer who sent the questionnaire.',
  title: 'A name to find it by later. Leave blank to use the file name.',
  due: 'When the customer needs the answers back.',
  answer: 'The answer as it will go to the customer. Approved answers are added to your answer library for next time.',
  reject: 'Why the drafted answer is not right. You can then write your own.',
  libraryQuestion: 'A question customers often ask, in their usual wording.',
  libraryAnswer: 'Your approved answer. Drafts reuse it when a similar question comes up.',
};
