/* Help text for Futran staff during fieldwork, findings and scoring. */

export const tierHelp = {
  tier: 'Tier 1 baseline, Tier 2 elevated, Tier 3 high risk. Raising the tier re-sends confirmation links to the named users.',
  rationale: 'Why this tier, especially where it differs from the proposed tier. Final tiers are approved at sign-off 5.',
  aedt: 'Whether the tool is an automated employment decision tool under NYC Local Law 144. An in-scope tool needs an independent bias audit.',
};

export const evidenceRequestHelp = {
  description: "Describe the evidence precisely, for example 'Bias test results for the last two quarters'. The client sees this text as written.",
  dueDate: 'The client gets a reminder 3 days before this date.',
};

export const findingHelp = {
  title: "A short statement of the issue, for example 'No bias testing before deployment'. It heads the finding in the report.",
  severity: 'Rate the risk if the issue is left as it is. Critical and High findings need the quickest remediation; Observation is for improvements with no control failure.',
  control: 'The control or legal requirement the finding is measured against.',
  description: 'Condition, criteria, cause and effect: what you found, the requirement, why it happened and the risk that follows.',
  recommendation: 'What the client should do to close the finding, specific enough that the fix can be verified.',
  owner: 'The role or person at the client who should fix this, for example Head of HR.',
  reviewComment: 'Required when returning the finding. Tell the author what to change.',
  dismissReason: 'Why the finding does not stand. The reason is kept in the audit log.',
};

export const systemHelp = {
  useCases: 'The Tier 2 and 3 use cases this system supports. Every Tier 3 use case must map to a system.',
  name: "Leave blank to use the first use case's name. Use the client's own name for the system.",
  version: 'The version or release in production during the audit period.',
  builtBy: 'Who built the model: in-house, a vendor, open source customized by the client, or a mix.',
  vendor: 'The supplier, for vendor-built or hybrid systems. Add the vendor first if it is not listed.',
  reason: 'Why the system belongs in scope. The Engagement Manager sees this when approving.',
  department: 'The department that owns the system.',
  depth: 'Full covers §3 to §9. Light covers §3, §5, §7.2 and §9 and suits Tier 2 systems.',
  owner: 'The business person accountable for the system at the client.',
  technicalOwner: 'The engineer or administrator who maintains the system at the client.',
  tools: 'The AI tools from the inventory that make up this system.',
  declineComment: 'Needed to decline. The auditor who asked sees it.',
};

export const vendorHelp = {
  legalName: 'The full legal name of the AI vendor, as on the contract.',
  capability: 'What the vendor supplies, for example candidate ranking or document summarization.',
  personalData: "Whether the vendor processes personal data on the client's behalf.",
  agreement: 'Whether a business associate agreement (HIPAA) or data processing agreement is signed with the vendor.',
  lastReview: "The date of the client's last risk review of this vendor.",
  riskLevel: "The client's own rating of the vendor, or yours if the client has none.",
};

export const governanceSetupHelp = {
  items: 'Choose the items to ask the client about. Items marked EU operations only can be chosen when the client operates in the EU.',
  dueDate: 'The date the client should answer by. It defaults to the engagement letter date.',
};

export const scoringHelp = {
  rating: 'The final rating for this system. Choose a rating other than the computed one only with a written rationale.',
  ratingRationale: 'Required when the rating differs from the computed rating. It is shown with the score.',
  domainScore: 'Maturity from 1 (lowest) to 5. The proposed score comes from the share of checklist items confirmed with evidence, less 1 for each open High or Critical finding.',
  domainRationale: 'Required when the score is more than 1 away from the proposed score.',
  dismissDraft: 'Why the draft finding does not stand. Kept with the assessment.',
};

export const adequacyHelp = {
  note: 'Required when asking for changes. Say what makes the response inadequate, for example no owner for a High finding.',
};

export const remediationReviewHelp = {
  verify: "What you checked to confirm the fix, for example 'Reviewed approved procedure v1.2'.",
  reopen: 'What is still missing. The owner sees this and can mark the item done again.',
};
