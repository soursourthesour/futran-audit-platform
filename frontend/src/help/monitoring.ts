/* Help text for the refresh and review queue (M3), refresh alerts (M6), the litigation tracker (L1, L2),
   opportunities (S1) and automatic client alerts (A1). Written for Futran staff. */

export const refreshHelp = {
  runOnSchedule: "Runs the refresh automatically at the interval below. Each run only proposes changes; nothing reaches the law library until the Chief Auditor approves it.",
  check: "What Claude compares against the approved record in this run. Leave all ticked for a full check.",
  geographies: 'Which geographies Claude checks. Client geographies are the places your current clients operate in (from the new-client wizard and the applicability screen).',
  checks: 'What Claude looks for. Fewer checks make the run cheaper and faster.',
  sources: 'Claude searches only allowlisted sources. Law-firm alerts are secondary: a change that rests on one is always low confidence and needs a second reviewer.',
  alert: 'Who hears when the run finishes. The default comes from the refresh alert settings.',
  schedule: 'The refresh also runs on its own every few days with these settings. Runs that would cost more than the cap stop early and say which geographies were not checked.',
  everyDays: 'Days between scheduled runs. The default is 14.',
  costCap: 'The most one run may spend on Claude, in US dollars. The run stops at the cap and lists the geographies it did not check.',
  notifyClients: 'When you approve, a client alert for each affected client waits in Client alerts for your approval. Untick to approve without alerting clients.',
  updateLetters: 'When you approve, the change is added to the next version of each affected client’s intro letter. Untick if the change does not belong in the letter.',
  editValue: 'The value that will be published. Dates as YYYY-MM-DD. For requirements and role maps, enter the JSON object.',
  note: 'Your reason. It is kept with the decision in the audit log.',
  secondReview: 'Low-confidence and new-law changes need a second reviewer, who cannot also approve. Concur if the source supports the change; object if it does not.',
  reviewer: 'A QA Reviewer or legal reviewer. They get a notification with a link to this change.',
};

export const staffAlertHelp = {
  ccQa: "Copies the QA Reviewer on the alert, so a second reviewer sees proposed changes as soon as the run ends.",
  ccAdmin: "Copies the Futran Admin, who keeps the law library's sources and settings in order.",
  recipients: 'All Chief Auditors, or only the Chief Auditor who started the run. Scheduled runs always go to all Chief Auditors.',
  copy: 'People who get a copy in the app and by email.',
  when: 'Every refresh, including runs that find nothing new; only runs with changes; or only runs with a new law, a low-confidence change or five or more affected clients.',
  how: 'In the app (the bell in the header), by email, or both.',
  remind: 'If a change is still waiting (pending, held or with legal review) after this many days, the recipients get a reminder.',
  escalate: 'After this many days, the other Chief Auditor and the Futran Admin are told.',
  test: 'Sends a test alert to you with the current settings.',
};

export const caseHelp = {
  name: 'As the court styles it, for example “Mobley v. Workday, Inc.”.',
  geography: 'Shown in the tracker, for example “United States · federal”.',
  jurisdiction: 'The jurisdiction code, for example US, US-CO, EU or IN. The litigation refresh checks cases by jurisdiction.',
  area: 'The law or area the case is about, for example “Hiring discrimination (ADEA, Title VII)”.',
  court: 'The court or tribunal, as published.',
  docket: 'The case number or citation, as published.',
  stage: 'The stage the court record shows. Check the docket before quoting it to a client.',
  stageNote: 'A short qualifier, for example “Age collective preliminarily certified”.',
  description: 'What the case is about, in two or three plain sentences.',
  whyMatters: 'One point per line. Shown on the case record.',
  pointsFutran: 'For the Chief Auditor and the Sales Team. One point per line.',
  pointsClient: 'Sent in the client briefing as the to-do list. One point per line.',
  types: 'Register system types that are like the AI in the case.',
  uses: 'Words that, found in a system’s name or purpose, show a similar use. Separate with commas.',
  vendors: 'Vendor names to match, separated by commas. Leave empty to match any vendor.',
  impact: 'Match only systems that make consequential decisions about people.',
  sources: 'One source per line: title, a space, then the link. Court and regulator documents first.',
  laws: 'The laws the case interprets. The case then shows on each law’s record.',
  owner: 'Who in the Sales Team owns the new opportunities.',
};

export const oppHelp = {
  summary: "What was said or agreed, in a sentence or two, and the next step with a date. The note stays on the opportunity's history.",
  client: 'The client the opportunity is about.',
  service: 'What Futran would offer, in a few words.',
  kind: 'Remediation of a finding raised in a current engagement cannot be offered to that client.',
  why: 'Why now: the rule, date, case or request behind it.',
  value: 'Estimated value in US dollars.',
  owner: 'Sales Team member or Chief Auditor who owns it.',
  stage: 'New, contacted, proposal, won or lost.',
  nextStep: 'The next thing to do, with a date if there is one.',
  activity: 'A call, email, meeting, note or outcome. Kept on the opportunity.',
  approval: 'For a current audit client, the Chief Auditor approves any offer before it is sent.',
};

export const clientAlertHelp = {
  groups: 'The client groups that receive the alert (E3). AIComplianceTeam is kept by the client; when it is empty the alert goes to the Chief AI Compliance Officer.',
  approval: 'Whether each send waits for the Chief Auditor, the Sales owner, or goes out automatically.',
  emailLabel: 'The name of the email shown in the rules grid.',
  subject: 'Leave as written, or shorten. The client’s systems are counted in the generated subject.',
  intro: 'An optional opening paragraph above the list of affected systems and to-dos.',
};
