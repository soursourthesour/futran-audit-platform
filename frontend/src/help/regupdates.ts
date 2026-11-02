/* Help text for regulatory change alerts (screen 26), "What this means for you", new AI projects (screen 28) and
   reassessment triggers. Futran strings are written for the Legal/Compliance Reviewer and the Chief Auditor; client
   strings for the people who fill in or review a project. */

export const updateHelp = {
  changeType: 'What kind of change this is. A pending bill is not law yet: keep it as a watch item unless clients need to act now.',
  jurisdiction: 'Where the change applies. Clients are matched when they operate there (their geographies from set-up and the applicability screen), including every level above, so a federal change reaches every US client.',
  law: 'The law in the law library this update is about, if there is one. Linking it matches every client in scope of the law and lets you propose the law change for approval.',
  lawName: 'How the law, bill or rule is named in the list, for example "NYC Local Law 144" or "Great American AI Act (discussion draft)".',
  title: 'One line that says what changed, written for a compliance officer.',
  summary: 'What changed, who it affects and from when. Two or three sentences with the figures and dates from the source.',
  todos: 'What a client should do, one item per line. These become the to-do list in the client alert and on the client\'s "What this means for you" page.',
  effectiveOn: 'The date the change takes effect or the obligation starts. It appears in each matched client\'s deadline calendar. Leave blank for enforcement news with no date.',
  sourceUrl: 'The official source: the statute, the regulator\'s page, the court docket or the audit report. A second reviewer checks the update against it before it is published.',
  sourceName: 'Who published the source, for example "Office of the New York State Comptroller".',
  sourceQuote: 'The passage the update rests on, quoted exactly. It goes with the law-change proposal to Refresh and review.',
  features: 'The kinds of AI the change concerns. A client is matched when one of its register systems is of that kind. Leave empty to match every client in the jurisdiction.',
  watch: 'A watch item is shown to Futran only. It is not matched to clients, raises no reassessment and cannot be sent as an alert.',
  verifyNote: 'Anything not yet confirmed against an official source, for example an operative date. The reviewer sees it before publishing.',
  reviewNote: 'Your reason. Needed when you send the draft back; kept with the decision in the audit log.',
  serviceKind: 'The kind of work to offer. Remediation of a finding Futran raised in a current engagement is refused (independence rule), and an offer to a current audit client waits for the Chief Auditor.',
  service: 'How the opportunity is named in Opportunities.',
  fieldPath: 'Which fact of the law record changes. The change goes to Refresh and review, where the Chief Auditor approves it and a new law version is written.',
  newValue: 'The new value as it should appear in the law record. Dates as YYYY-MM-DD.',
  changeSummary: 'One line for the review queue saying what changes.',
  digest: 'Sends the client\'s Chief AI Compliance Officers one email a week listing the updates published for them. Off until you turn it on.',
  calendarClient: 'Show the dates for one client, or for every client you can see.',
  withdrawReason: 'Why the update is taken back, for example a source that was wrong. It stays in the audit log; clients no longer see it and it raises nothing new.',
};

export const projectHelp = {
  name: 'A short name for the project, as people in the company call it.',
  department: 'The department that will use the AI. Its Department Compliance Lead reviews the project.',
  tool: 'The product and vendor, or "Built in-house" if your own team is building it.',
  goLive: 'When you plan to start using it. Submit well before this date so the reviews can finish.',
  purpose: 'What the AI will do and for whom, in a sentence or two. Say whether a person can always take over.',
  type: 'The kind of AI. A chatbot or writing assistant is a generative AI chat tool; a feature inside software you already use is an embedded AI feature.',
  sourcing: 'Bought from a vendor, built in-house or by a contractor, or a free or personal tool (free and personal accounts make the project at least Tier 2).',
  jurisdictions: 'Where the people who use it, or are affected by it, are. The laws that apply are matched from these places.',
  data: 'Every kind of data the AI will receive or produce. Choose "None of these" only if it uses no personal or confidential data at all.',
  subjects: 'Whose data it uses or whom its output is about.',
  decisions: 'Whether the AI makes, or substantially assists, decisions about people such as hiring, credit, housing, insurance, health care or education. This decides Tier 3.',
  publicFacing: 'Whether members of the public interact with it directly, for example by chatting with it.',
  autonomy: 'For an AI agent: whether it only suggests, acts with a person\'s approval, or acts on its own.',
  recommendation: 'Your recommendation to the Chief AI Compliance Officer, who makes the decision.',
  reviewComment: 'What you checked. Needed when you recommend conditions or rejection: say which conditions, or why.',
  decision: 'Approved projects are added to the AI system register as proposed systems (or linked to the system you choose). Conditions are tracked until they are closed.',
  decisionNote: 'Your reasons. Needed for a rejection; sent to the person who submitted the project.',
  conditionText: 'What must be done, for example "Complete a DPIA before go-live".',
  conditionOwner: 'Who does it. They can mark it met; you close it.',
  conditionDue: 'When it must be done.',
  linkSystem: 'If this project is a change to a system already in the register, choose it here instead of adding a new one.',
  metNote: 'How the condition was met, and where the evidence is.',
};

export const triggerHelp = {
  type: 'What changed. Version, data, jurisdiction, people affected and vendor changes are also detected automatically when the register record is edited.',
  detail: 'One line on what changed, for the person who reassesses it.',
  note: 'What was reassessed and the outcome, or why no reassessment is needed. A resolution is added to the system\'s history log.',
};
