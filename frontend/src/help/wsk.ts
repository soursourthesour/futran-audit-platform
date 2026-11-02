/* Help text for the bias test calculator (screen 29), the heat map and lineage (35), benchmarking (34) and annual reviews. */

export const biasHelp = {
  file: 'A CSV file with one row per person the tool assessed: id, selected (yes or no) or score, sex and race_ethnicity. Leave sex or race blank when it is unknown. Optional columns: age_band and qualified (yes or no, for the equal opportunity difference).',
  existing: 'A CSV the client uploaded to this engagement, for example in answer to an evidence request. The run reads it from the client’s tenant.',
  method: 'Selection rate: the share of each category moved forward or given the classification. Scoring rate: the share of each category scoring above the median of the whole sample. Both are defined in 6 RCNY § 5-300.',
  dataSource: 'Where the data came from and what it covers (tool, employer, roles, period). It goes into the public summary, which must explain the source of the data (6 RCNY § 5-303).',
  excludeSmall: 'The rule lets the independent auditor leave a category under the small-category share out of the impact ratios. Its applicants and rate are still reported, with your justification.',
  justification: 'Why each excluded category was left out of the impact ratios. The rule requires it in the published summary.',
  endpointLabel: 'A name for the chatbot or endpoint under test, for example “Careers chatbot (sandbox)”.',
  decisionNote: 'Your reason. Required to reject the results; recorded with the decision.',
};

export const heatHelp = {
  department: 'Show only systems owned by this department. The findings view follows the same systems.',
  buildType: 'Show only systems built this way.',
  framework: 'Show only findings that cite a control of this framework.',
};

export const insightHelp = {
  client: 'The client to compare with its peers. Only clients with a signed report have figures.',
  consent: 'Tick when the client agreed to anonymous benchmarking in its engagement letter. Without it the client is neither compared nor counted as a peer.',
  consentNote: 'Where the consent is recorded, for example the clause of the signed engagement letter.',
};
