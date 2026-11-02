/* Help text for the policy builder (27), AI literacy training (33) and the Trust Center (32). Written for the client's
   compliance team, except where marked for Futran staff. */

export const policyHelp = {
  template: 'Futran writes and versions these templates. Your answers fill them in; you can then edit the text before it goes for approval.',
  commitment: 'The governance commitment this policy answers. When the policy is approved and published, the commitment closes with the policy as its evidence.',
  regenerate: 'Rebuilds the draft from the template and your answers. Changes you made to the text by hand are replaced.',
  blockType: 'Policies use headings, paragraphs and lists only, so they print and read the same everywhere.',
  blockText: 'For a list, put one item per line.',
  returnNote: 'Tell the author what needs to change. They see this note on the draft.',
  ackGroups: 'Who is asked to read and acknowledge the policy. Each person gets a personal link; people who have already acknowledged are left out.',
  ackDepartments: 'Leave empty to send to everyone in the chosen groups.',
  reminders: 'Reminders go only to people who have not acknowledged yet.',
  futranNote: 'What you would like Futran to look at. Futran replies with a quote for advisory hours; nothing is charged until you accept it.',
  futranTeam: 'Futran staff who wrote or tailored this policy. None of them may be Lead Auditor on a later audit of this client (independence rule).',
};

export const trainingHelp = {
  modules: 'Futran modules to assign. Each takes 10 to 20 minutes on a phone or computer and ends with a short quiz.',
  audienceKind: 'Assign to whole departments, to everyone who holds a platform role, or to an email group from Groups.',
  departments: 'Everyone in the directory who belongs to these departments.',
  role: 'Everyone with a login who holds this role.',
  groups: 'Email groups set up under Groups. Nested groups are included.',
  due: 'The date by which people should finish. It appears in the email and on their training list.',
  reminders: 'Days after the email when a reminder goes to people who have not finished. Leave empty for no reminders.',
  targetPct: 'The share of assignments that should be complete. Departments below it show in red and raise a monitoring alert.',
  targetDate: 'The date the target applies from. Before it, a department below target shows as needing attention; after it, as failed.',
};

export const trustHelp = {
  slug: 'The last part of the public address, for example abc-corp gives /trust/abc-corp. Lower-case letters, numbers and hyphens.',
  heading: 'The main heading of the public page. A change goes public only after you approve it and Futran confirms it; until then the confirmed heading, or the standard one, is shown.',
  intro: 'One or two sentences on how your organization uses AI. Like the heading, it goes public only after you approve it and Futran confirms it.',
  contact: 'Where people send questions about your use of AI. Shown on the page.',
  live: 'When ticked the page is public at its address. Only items that are approved and confirmed by Futran appear on it.',
  access: 'Public shows everything. NDA click-through asks visitors to accept your terms before they open detailed documents such as policies.',
  nda: 'The terms a visitor accepts before opening detailed documents. Their name, email and company are recorded.',
  indexable: 'Lets search engines list the page. Leave unticked to keep it out of search results; people with the link can still open it.',
  kind: 'What the item shows. Badge, bias audit summary and policy items are built from your records and cannot be typed.',
  itemTitle: 'The card heading.',
  itemBody: 'What the card says. Keep it to what the audit found: Futran checks it against the signed report before it is published.',
  linkUrl: 'Optional. A web address starting https:// or an email link starting mailto:.',
  showRating: 'Shows the overall rating from the signed report on the badge. Leave unticked to show only the engagement, period and report reference.',
  confirmNote: 'For Futran staff: where in the signed report the claim is supported.',
  returnNote: 'For Futran staff: what does not match the signed report, so the client can correct it.',
};
