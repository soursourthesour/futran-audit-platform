/* Help text for the client portal and the no-login phone forms. Written for client staff, not auditors. */

export const inviteHelp = {
  password: 'A passphrase of three or four unrelated words is easiest to remember. Passwords found in breach lists are refused.',
  confirm: 'Type the same password again to rule out a typo.',
};

/** Keyed by the getting-started item key from the API. */
export const checklistHelp: Record<string, string> = {
  guide: 'How to sign in, set up sign-in codes, the audit timeline and who your Futran contacts are. Mark it as read once you have been through it.',
  sign: 'Sets out the audit period and the laws, sites and departments in scope. The Chief AI Compliance Officer signs it; this is sign-off 1.',
  nominate: 'Name your Executive Sponsor, Data Protection Officer and a Compliance Lead for each department, or mark a role as not appointed. Done once every role is covered.',
  departments: 'Check the department list Futran drafted from the scope. Add or exclude departments, then confirm the list.',
  users: 'Add only people who need to sign in: role holders, Department Compliance Leads and contributors. Everyone else takes part through the attestation link.',
  notice: 'Tells staff what the attestation collects and who sees it. Circulate it before launching the attestation; the Chief AI Compliance Officer acknowledges it here.',
  governance: 'Tell Futran which AI governance bodies, policies and named owners exist today. Anything not yet in place becomes a dated commitment.',
};

export const peopleHelp = {
  departments: 'Departments in the audit scope. Each needs a Department Compliance Lead. Exclude a department that does not use AI; it stays listed but drops out of scope.',
  newDepartment: 'Add a department missing from the list, using the name your staff know it by. You can also upload the department CSV.',
  users: 'People who need to sign in. Upload the user CSV (first name, last name, email, job title, department, role, location) or add people one at a time. Each person gets an invitation email.',
  signOffRoles: 'Roles that sign stages of the audit. To name someone, add them as a user with that role.',
  notAppointed: 'Tick if your organization has no one in this role. The Chief AI Compliance Officer then covers it.',
  firstName: 'As it should appear on sign-offs and in the audit log.',
  lastName: 'As it should appear on sign-offs and in the audit log.',
  email: 'Their work email. The invitation goes here and it becomes their sign-in name.',
  jobTitle: 'Shown next to their name on sign-offs and in the users list.',
  role: "Contributors record use cases. Department Compliance Leads review and approve their department's inventory. The other roles sign stages of the audit.",
  department: 'The department this person works in. Department Compliance Leads and Contributors work within one department.',
};

export const governanceHelp = {
  answerRole: 'In place: name the people or committee today. Will constitute: give a target date and an interim owner; it becomes a tracked commitment. N/A: give the reason.',
  answerDocument: 'Upload the current approved version. Will create: give a target date and an interim owner; it becomes a tracked commitment. N/A: give the reason.',
  chair: 'The person who chairs the committee today.',
  memberCount: 'Total members, including the chair.',
  meets: 'How often the committee meets in practice, as its minutes show.',
  member: 'One member per row. Add each member, or upload the terms of reference that list them.',
  name: 'The person who holds this role today.',
  title: 'Their job title.',
  targetDate: 'The date by which it will be in place. Futran tracks it as a commitment and follows it up in remediation.',
  interimOwner: 'The person accountable until it is in place, usually the Chief AI Compliance Officer.',
  plannedMembers: 'The roles or people expected to sit on it, for example HR, Legal and Data Science.',
  naReason: "Why this does not apply to your organization, for example 'No AI is used in hiring'. The auditor reviews every N/A answer.",
  accurate: 'Confirms the answers reflect your organization today. Answers lock when submitted; ask your Chief Auditor if one must change.',
};

/** Section 4 policy and accountability facts, keyed by the field key from the API. */
export const governanceExtraHelp: Record<string, string> = {
  board_oversight: 'The board member or committee that oversees AI risk, by name.',
  policy_owner: 'The person who owns and updates the AI policy.',
  policy_last_updated: 'The date the current AI policy was approved or last revised.',
  policy_covers_employees: 'Whether the policy sets rules for staff using AI tools at work, including public tools such as ChatGPT.',
  policy_covers_client_facing: 'Whether the policy covers AI that customers, applicants or patients interact with or are affected by.',
  risk_appetite: 'A board-approved statement of how much AI risk the organization accepts. Informal means it is understood but not written down.',
  incident_escalation: 'Who is told when an AI system causes harm or fails, and in what order.',
  model_risk_manager: 'For banks and financial services: the person who runs model risk management. Leave blank if not applicable.',
  data_steward: 'The person accountable for the quality and use of the data AI systems rely on.',
  ethics_lead: 'The person who leads on AI ethics, if the role exists.',
  security_owner: 'The person accountable for the security of AI systems and AI vendors.',
  privacy_officer: 'Your privacy officer or Data Protection Officer.',
  third_party_owner: 'The person who approves and monitors AI bought from vendors.',
  raci_exists: 'Whether a written RACI sets out who is responsible, accountable, consulted and informed for AI decisions.',
};

export const attestationLaunchHelp = {
  departments: 'The departments whose staff will be sent the link. All departments in scope are ticked to start with.',
  closesOn: 'The link stops accepting answers at the end of this day. Two weeks is usual.',
  policyVersion: 'The version of your AI use policy that staff acknowledge, for example 1.0. It is recorded with each answer.',
};

export const phoneAttestationHelp = {
  name: 'Your full name. Managers see department totals only, never your individual answers.',
  email: 'Optional. Give it if you might want to change your answers later; answering again with the same email replaces them.',
  department: 'The department you work in. If you work across several, choose the one where you spend most time.',
  tools: 'Tick every AI tool you have used for work, including AI built into other apps. For each one, say which account you use.',
  toolName: 'The name of the app or feature, for example Copilot in Excel or the AI assistant in Salesforce.',
  account: 'A company account is paid for and managed by your employer. A personal account is one you signed up for yourself, free or paid.',
  none: 'Tick if you do not use any AI tool for work. You then go straight to the policy.',
  purposes: 'What you use AI tools for. Tick everything that applies, even if only now and then.',
  data: 'Think about what you paste, type or upload. Personal information means anything about an identifiable person, such as a CV or a customer record.',
  policy: 'Tick once you have read the policy above. Your acknowledgement is recorded with the policy version.',
};

export const namedUserHelp = {
  training: 'Any training on using this tool safely counts, for example a vendor course or an internal session.',
  policy: "Your organization's AI use policy, shown above.",
  oversight: 'Whether you check the AI output before anyone acts on it, as described. Answer No if someone else does the check or it is skipped.',
  reason: 'Optional. Say what is missing, for example training not yet booked. It helps your organization close the gap.',
};

export const useCaseHelp = {
  name: "A short name for this use, for example 'Résumé screening for NYC roles'. Record one use case per purpose, even when the tool is the same.",
  department: 'The department that owns this use. Its Department Compliance Lead reviews the entry.',
  tools: 'Every AI tool used for this purpose. Add a missing tool from the inventory page first. A personal or unknown account raises the proposed tier.',
  purpose: 'What the tool does and how its output is used, in a sentence or two. Say who acts on the output.',
  data: 'Tick every kind of data typed, uploaded or connected to the tool. Personal, health, client or confidential data makes it at least Tier 2.',
  impact: 'How the output feeds into decisions about people. Substantially assisting or making decisions on hiring, promotion, credit, housing, insurance or health makes it Tier 3.',
  role: 'The job role that uses the tool, for example Recruiter.',
  headcount: 'How many people in that role use it.',
  frequency: 'How often a typical person in that role uses it.',
  namedUsers: 'Name each person who uses the tool. Tier 2 and 3 use cases need a work email for each; people without a login are sent a short confirmation link.',
  personName: 'Full name of the person.',
  personEmail: 'Their work email. People without a platform login receive a confirmation link here.',
  oversightRole: "What this person checks before the output is used, for example 'Reviews the ranked list before interviews'. Required for Tier 3.",
  returnComment: 'Say what needs to change. The submitter sees the comment and can resubmit.',
};

export const toolHelp = {
  vendor: 'The company that supplies the tool, for example Workday or OpenAI.',
  product: 'The product or feature name, for example Recruiting AI or ChatGPT.',
  accountType: 'Company accounts are licensed and managed by your organization. A personal or unknown account raises the tier of every use case that relies on it.',
  training: "Whether the vendor may use what your staff enter to train its models. Check the contract or the vendor's data terms; choose Not known if unsure.",
  plan: 'The subscription level, for example Enterprise, Team or Plus.',
  retention: "How long the vendor keeps prompts and outputs, as the contract or data terms state, for example '30 days, then deleted'.",
};

export const documentHelp = {
  upload: 'Upload the current approved version. PDF, Word, Excel, PowerPoint, text and image files are accepted; upload several files if the document is in parts.',
  notAvailableNote: 'Say whether it exists in another form or when it will be ready. The auditor records a missing document as a finding.',
  evidenceAnswer: 'Answer in writing when the evidence is not a document, for example how a check is done in practice.',
};

export const responseHelp = {
  response: 'Agree or partially agree if you accept the finding, or part of it. Disagree if you do not, and give your reasons below.',
  plannedAction: "What you will do, specific enough to check, for example 'Approve and publish a bias testing procedure'. If you disagree, give your reasons instead.",
  owner: 'The person accountable for completing the action. They can mark it done in the remediation tracker.',
  dueDate: "The date the action will be complete. Futran reviews whether it is realistic for the finding's severity.",
};

export const remediationHelp = {
  done: 'Describe what was done and where the evidence is. Upload supporting files under Documents and refer to them here.',
};

export const signHelp = {
  typedName: 'Type your full name. Typing it and selecting Sign is your signature, recorded with the date and time.',
  agree: 'Confirms you have read the document. You cannot sign until this is ticked.',
  returnComment: 'Say what needs to change. The preparer sees the comment and sends a corrected version.',
  correction: 'Explain what must change. A new version opens for signature and the signed version is kept.',
};

export const reportHelp = {
  commitment: 'Commit to the remediation plan as agreed, or record that you dispute one or more findings. Signing acknowledges receipt either way.',
  disputed: 'Tick each finding you dispute. The dispute is recorded with your acknowledgement.',
};
