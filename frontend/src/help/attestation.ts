/** Field help for the attestation changes of 27 October: agents, "Something else", the answers grid and the in-app line item. */
export const attestationFormHelp = {
  tools: 'Tick every AI tool you have used for work, including AI built into other apps. For each one, say which account you use.',
  agents: 'An agent does things for you rather than only answering: it sends messages, updates records, writes code or runs steps on its own. Tick each one you have set up or use.',
  toolName: 'The name of the tool, for example Perplexity or the AI assistant in Salesforce.',
  appName: 'The name of the app or feature, for example Copilot in Excel or the AI assistant in Salesforce.',
  agentName: 'The name of the agent or what it does, for example "Invoice chaser" or "Candidate outreach bot".',
  inHouseAgent: 'An agent your company built or configured itself. It is treated as running on a company account.',
  purposeOther: 'In a few words, what else you use AI for, for example translating contracts or preparing board packs. Up to 200 characters.',
  identity: 'Taken from your account, so you are not asked again. If your department is wrong, tell your Client Admin.',
  linkEmail: 'The address this link was sent to. Your answer is recorded against it, and a later answer from the same address replaces this one.',
};

export const attestationAnswersHelp = {
  department: 'Move the answer to the department the person actually works in. The change is logged with the old and new department.',
  name: 'Correct the spelling of the name only. The change is logged.',
  purposeOther: 'Correct what the person wrote under "Something else". Their ticked answers are not changed.',
  toolName: 'Correct the name the person typed, for example a misspelt product. The tool they ticked and the account stay as they answered.',
  reviewerNote: 'Your note on this answer, for example "confirmed with the manager". Visible to the CAICO, DPO and Futran auditors.',
  removeReason: 'Required. For example "duplicate of an earlier answer" or "test answer". Removed answers stop counting in totals but are kept in the audit log.',
};

export const sendAttestationHelp = {
  send: 'Adds an "AI use attestation" item for everyone in your organization who has accepted their invitation, and emails them. People who accept later while the campaign is open get it automatically.',
};
