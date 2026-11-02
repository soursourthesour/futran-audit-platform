/** Help text for wave 3 WS-L: comments (F18), the public API and webhooks (F17), agent oversight (F14), platform trust (F19). */

export const commentHelp = {
  body: 'Type @ and a name to mention someone. They get a notification in the app and an email.',
  visibility: 'Internal comments are seen by the Futran team only. Shared comments are also seen by the client people who work on this item.',
  draftOnly: 'Comments on a finding that is not yet approved stay internal.',
  clientNote: 'Your comment is shared with the Futran audit team and the people at your organization who work on this item.',
  edit: 'You can edit a comment for 15 minutes after posting it.',
  withdraw: 'Withdrawing hides the text from everyone. The comment stays in the record with your name and the time.',
};

export const apiHelp = {
  name: 'The system that will use this client, for example "ServiceNow GRC sync". It appears in the audit log beside every call.',
  scopes: 'Give only the access the system needs. A token can never do more than its client\'s scopes.',
  rate: 'Calls a minute. Further calls get "429 Too many requests" until the minute has passed.',
  owner: 'The Client Admin who answers for this client. Changes the client makes through the API are recorded as theirs.',
  secret: 'Copy the secret now. It is shown only once and stored only as a hash. If it is lost, issue a new one.',
  url: 'A public HTTPS address. Addresses on a private network (localhost, 10.x, 192.168.x, 169.254.x and similar) are refused.',
  events: 'The events this address receives. Each delivery is signed with your signing secret.',
  signing: 'Check each delivery: compute HMAC-SHA256 of "<timestamp>.<body>" with this secret and compare it with the v1 value in X-Futran-Signature. Reject old timestamps.',
};

export const agentHelp = {
  tools: 'Each tool or API the agent can call. "Acts" means it changes something outside the platform: sends, pays, books, deletes.',
  needsApproval: 'Tick when a person approves each use of this tool before it runs.',
  permissions: 'The data and systems the agent may use, one per line.',
  approvalPoints: 'Where a person must approve before the agent acts, one per line.',
  autonomy: 'How far the agent acts without a person approving each action.',
  killSwitch: 'How the agent is stopped at once, and who can do it.',
  killTested: 'The last date someone stopped the agent to check the kill switch works.',
  rateLimits: 'Limits on how often the agent may act, for example 50 emails an hour.',
  sampleSize: 'How many decisions to review. They are drawn at random from the decision log.',
  period: 'How far back to draw decisions from.',
  seed: 'Leave blank for a new random sample. Enter the seed of an earlier sample to draw the same decisions again.',
  verdict: 'Was the agent\'s decision right under its registration and the client\'s policy?',
  note: 'Required unless the decision was appropriate: say what was wrong or what to follow up.',
  conclusion: 'Your conclusion on the sample, for the working papers.',
};

export const trustHelp = {
  owner: 'The person at Futran who runs this control and keeps its evidence.',
  status: 'Implemented: in place. Tested: an auditor has tested it for the SOC 2 report.',
  evidence: 'A link to the evidence (policy, ticket, report) or where it is kept.',
  reviewed: 'The date the owner last checked the control still works.',
  months: 'How often the control is reviewed.',
  notes: 'Anything the next reviewer should know.',
  code: 'The trust services criteria reference, for example CC6.1.',
};
