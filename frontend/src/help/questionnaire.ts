/* Help for the AI system questionnaire (client pre-fill and auditor assessment).
   Question-specific guidance comes from the question bank (help_text); these cover the parts every question shares. */

export const questionHelp = {
  status: 'Answered: it is in place today. Planned, not yet in place: it is planned but not done, and the auditor treats it as not in place. Not applicable: give the reason.',
  naReason: 'Why the question does not apply to this system. The auditor reviews every N/A answer.',
  planned: "What is planned and by when, for example 'Bias testing procedure to be approved by the AI committee in March'.",
  detail: 'Context the auditor should know, such as where the evidence is kept or who to ask.',
  detailNamed: 'The detail that goes with the answer above. The auditor checks the two together.',
  evidence: 'Files that support the answer, such as a policy, a test report or a screenshot. The auditor checks them before verifying the answer.',
  sourcePerson: 'Who gave this answer in interview.',
  sourceTitle: 'Their job title. Both are recorded with a verified answer.',
  verified: 'Tick once you have seen the evidence or confirmed the answer in interview. A verified answer needs a source person.',
};

/** Used only when the question bank has no guidance for a question. */
export const questionTypeHelp: Record<string, string> = {
  single: 'Choose the answer that describes the system as it runs today. Add context in the detail box.',
  yes_no: 'Answer for the system as it runs today. If it exists only informally, say so in the detail box.',
  yes_no_unknown: 'Answer for the system as it runs today. Choose Unknown rather than guess; the auditor follows it up.',
  multi: 'Tick every option that applies today.',
  date: 'The date from your records. Say in the detail box if it is approximate.',
  number: 'A figure from your records where one exists. Say in the detail box if it is an estimate.',
  percent: 'A percentage from your records where one exists. Say in the detail box if it is an estimate.',
  person: 'The person who holds this responsibility today, with their job title.',
  text: 'Answer in plain terms as things stand today. The auditor checks it in interview.',
  long_text: 'Answer in plain terms as things stand today. The auditor checks it in interview.',
};
