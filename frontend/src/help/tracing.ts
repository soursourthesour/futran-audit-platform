/** Help text for the tracing add-on: R7 tracing and incidents, R8 unlock (spec §27.3). */

export const unlockHelp = {
  systems: 'Tick each AI system to trace. Recommended ones are ticked for you: Tier 3 systems, agents that take actions, and systems with a past incident.',
  plan: 'Per system is priced per system each month. All Tier 2 and 3 covers every such system, including ones added later. Enterprise covers every system and is agreed with Futran.',
  approver: 'Your Executive Sponsor approves the purchase. They get a task in the platform and an email.',
  start: 'A trial runs for 30 days from approval and then continues as a paid subscription unless it is cancelled.',
  note: 'Anything Futran should know, such as a go-live date or the incidents you need to report. Futran\'s sales team sees this note.',
  decision: 'Approving opens the Tracing tab on the systems the request covers. Futran\'s sales team then confirms the order with you.',
  declineReason: 'Required when declining. It is sent to the person who asked.',
  cancelReason: 'Why the add-on is no longer needed. Records already made stay on file and can be exported.',
};

export const traceHelp = {
  decision: 'Show only actions that were allowed, blocked or handed to a person.',
  period: 'How far back to show actions.',
  importFile: 'A CSV or JSON file from GuardRail or the agent\'s own logs. Columns: time, session, action, tool, data touched, decision, policy, approver or note, agent, event id. Every row is checked first; nothing is saved while any row has an error. Rows whose event id is already held are skipped.',
  at: 'When the agent took or tried the action, in your local time.',
  session: 'The session or conversation the action belongs to, as the agent logs it.',
  action: 'What the agent did or tried to do, in plain words.',
  tool: 'The tool or API the agent called, for example crm.create_lead.',
  data: 'The data the action read or changed.',
  decisionField: 'Allowed: the action went ahead. Blocked: a control stopped it. Escalated: it was handed to a person.',
  policy: 'The GuardRail policy or other control that decided.',
  approver: 'Who approved it, or the control\'s note.',
  agent: 'The agent\'s identity as it appears in the logs.',
  guardrailToken: 'Your organisation\'s own GuardRail access token, from GuardRail\'s settings. It is stored encrypted and never shown again. Syncs read only the policies this token can read.',
};

export const incidentHelp = {
  description: 'What happened, to whom and how it came to light. This becomes the entry in the system\'s history log.',
  foundAt: 'When your organization noticed it or was told about it. Regulator clocks start here: CERT-In counts 6 hours from noticing, the EU AI Act counts days from becoming aware.',
  severity: 'Your own rating. Serious incidents under the EU AI Act are recorded in the next question.',
  serious: 'A serious incident under EU AI Act Art. 3(49) leads, directly or indirectly, to death or serious harm to health, a serious and irreversible disruption of critical infrastructure, a breach of EU law protecting fundamental rights, or serious harm to property or the environment. It must be reported to the provider at once and to the market surveillance authority within the period shown.',
  risk: 'Tick if using the system as instructed may present a risk to health, safety or fundamental rights (EU AI Act Art. 79(1)). The deployer must tell the provider or distributor and the authority without undue delay and suspend use.',
  cyber: 'Tick if this is a cyber security incident of a kind listed in Annexure I of the CERT-In Directions, such as unauthorized access, a data breach or an attack on an AI system. It must be reported to CERT-In within 6 hours of noticing it.',
  agNotice: 'Colorado SB 26-189 has no duty to report to the Attorney General. If the Attorney General sends a notice of violation, enter the day it arrived: the law gives 60 days to cure the violation.',
  people: 'How many people were affected, as far as you know now.',
  cause: 'What caused it, as far as you know now.',
  containment: 'What was done to stop it and limit the harm.',
  fix: 'The lasting fix, and how you checked it works.',
  owner: 'The person who sees the incident through to closure. They get the deadline reminders.',
  history: 'If this incident is already in the history log, link it here instead of adding a second entry.',
  doneAt: 'When the notice was sent or the report filed.',
  reference: 'The report, ticket or email reference, so an auditor can trace it.',
  naReason: 'Why this notice does not apply, for example "Not a high-risk system under Annex III". The reason stays on record for the auditor.',
  closedOn: 'The day the incident was resolved.',
  bulkOwner: 'The owner for every selected incident.',
};
