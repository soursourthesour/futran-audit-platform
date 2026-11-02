/* Help text for integrations and AI discovery (screen 30) and continuous monitoring (screen 31). Written for the client's
   Client Admin and Chief AI Compliance Officer, and for Futran auditors reading the client page. */

export const integrationsHelp = {
  page: 'Read-only connections. Results are grouped by tool and department; what individual people browse is never shown.',
  okta: 'Install the Futran API service integration from the Okta Integration Network with the read scopes okta.apps.read and okta.users.read, then enter the domain, client ID and secret it gives you.',
  oktaDomain: 'Your Okta address, for example yourcompany.okta.com.',
  oktaClientId: 'Shown on the Futran integration in your Okta Admin Console after you install it.',
  oktaSecret: 'Shown once when the integration is installed. It is stored encrypted and used only to read app assignments.',
  microsoft: 'A Global Administrator approves read-only access (enterprise apps, app consents, Copilot licences and usage). Nothing is written to your tenant.',
  google: 'A Workspace super administrator signs in once and allows read-only access to the OAuth token log, Gemini activity and the user directory.',
  expense: 'A CSV export from your expense or card system with a description or merchant column. Rows are matched to Futran’s AI vendor list; the file itself is not kept.',
  casb: 'A CSV export from your CASB or web proxy with a domain or URL column. Traffic is counted per department while the file is read; no person’s browsing is stored.',
  file: 'CSV, up to the platform’s upload limit. Headers such as Description, Merchant, Department, Employee, Destination host or URL are recognised.',
  declared: 'Undeclared means no employee named this tool in the latest attestation.',
  confirm: 'Adds the tool to your AI inventory and asks the department’s compliance lead to describe the use case.',
  map: 'Links this finding to a tool already in your AI inventory, for example a personal ChatGPT subscription to your ChatGPT Enterprise entry.',
  mapTool: 'The inventory tool this discovery belongs to.',
  dismiss: 'Say why this is not an AI tool your people use for work. The Futran auditor sees the reason.',
  reason: 'For example: a trial during a vendor demo, already cancelled; or a refund for a personal purchase.',
  people: 'Names are shown only to Futran auditors, only for tools used in a Tier 2 or Tier 3 use case, for the named-user check. Each view is logged.',
  testConsent: 'Test mode. This page stands in for the provider’s consent screen; no real account is used and nothing leaves the platform.',
  testDomain: 'The domain your administrator signs in with. The platform checks it is one of your organisation’s own email domains.',
};

export const monitoringHelp = {
  page: 'Checks run monthly and after each connector sync or upload. Your Futran auditor sees the same alerts. Monitoring never changes a signed report; results feed the next annual review.',
  plan: 'Monitor plans add monthly connector re-syncs, automatic checks and alerts between audits. Audit only keeps the annual audit.',
  nextReview: 'The date Futran has agreed for the next annual review. Left blank, it is twelve months after the latest signed report.',
  note: 'For example the order form or the agreed scope. Shown on the client page only.',
  runNow: 'Runs every check now, without waiting for the monthly run.',
};
