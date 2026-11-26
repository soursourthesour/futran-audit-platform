# Futran Audit Platform: website library API

Version 1, 26 November 2026. Base URL: `https://<platform host>/api/public/v1/library`

## Overview

The website library API lets Futran's public website show the law library and the AI litigation tracker as they appear in the Futran Audit Platform. It is read-only. It serves:

| Endpoint | What it returns | Same data as in the app |
|---|---|---|
| `GET /laws` | Laws in the law library: search, filters, sort, pagination | Law library (`/reg`) |
| `GET /laws/{law_id}` | One law's full record | Law record (`/reg/{law_id}`) |
| `GET /cases` | AI court cases: filters, search, sort, pagination | Litigation tracker (`/litigation`) |
| `GET /cases/{case_id}` | One case's full record, with the laws it interprets | Case record (`/litigation/{case_id}`) |
| `GET /meta` | Filter values, record counts and when each library was last refreshed | Filters and tiles on both screens |

The website sees the same records, fields and filters as Futran staff, with one boundary: nothing that ties a law or a case to a Futran client or to Futran staff leaves through this API (see [What is excluded and why](#what-is-excluded-and-why)). Only published records are served: a law's current approved version, approved obligations and the cases in the tracker. Anything still waiting for review in the refresh pipeline is not served until a person approves it.

The schema document is at `/api/public/v1/library/openapi.json`. On a test-mode server the Swagger page is at `/api/public/v1/library/docs`.

All dates are ISO 8601 (`2027-01-01`). All times are UTC, in ISO 8601 without an offset (`2026-11-26T02:00:41.512309`), as in the rest of the platform.

## Freshness

Both libraries are kept current by the platform's scheduled refresh (laws and litigation, using the connected AI provider). The refresh proposes changes; a person on the Futran team approves each one before it goes live. The API serves what is live: the platform's own cache is dropped as soon as a record changes, so the next request gets the change. A website that follows the caching headers below shows it within 5 minutes (up to 15 while it revalidates a stale copy in the background).

`GET /meta` gives `laws.last_refreshed_at` and `cases.last_refreshed_at`: when the last refresh run of that library finished (completed, partly completed or stopped at its cost cap; a failed run does not count). Every response also carries the header `X-Library-Last-Refreshed` for its library (`/meta` carries the later of the two). The value is `never` if no refresh has run.

## Authentication

### Getting a key

A Futran Admin creates the key in the platform: **Administration > Website API keys > New website key**.

- **Name**: which website or environment uses it, for example "Futran website (production)".
- **Allowed origins**: leave empty for a key used from the website's server (recommended). List origins, such as `https://www.futransolutions.com`, only for a key that must be called from the browser. An origin is `https://host[:port]`; `http://` is accepted for `localhost` and `127.0.0.1` only. No paths or wildcards.
- **Calls a minute**: the key's rate limit, 1 to 1,200. Default 120.

The key is shown once. The platform keeps only a SHA-256 hash of it and the first 12 characters (for example `fwl_Q2hvY2tz`) so keys can be told apart. Copy it into the website team's password manager or secrets store. If it is lost or exposed, revoke it on the same screen and create a new one; a revoked key gets 401 at once. Creating and revoking keys is recorded in the audit log. Website keys are not tied to any client organization and cannot reach anything but this API.

### Sending the key

Send it in the `X-API-Key` header:

```
X-API-Key: fwl_Q2hvY2tzX2V4YW1wbGVfa2V5X25vdF9yZWFsXzAwMDAwMDA
```

`Authorization: Bearer <key>` is also accepted. A session cookie is not: signing in to the platform does not open this API.

## Endpoints

Every endpoint takes only the parameters listed for it; any other parameter is refused with 422. Text parameters are case-insensitive where noted.

### GET /laws

Laws in the law library, in the library's order (region, then geography, then name).

| Parameter | Values | Default |
|---|---|---|
| `q` | Words to search for. A law matches when every word is in its name, label, citation or geography, or when the phrase is in one of its requirements. Case-insensitive. Up to 200 characters. | none |
| `region` | `us_federal`, `us_states`, `eu`, `india`, `uk`, `canada`, `other`, `framework` (from `/meta`) | all |
| `status` | `in_force` (includes in force, phased), `in_force_phased`, `enacted_not_in_force`, `phased`, `delayed`, `guidance`, `repealed`, `pending` | all |
| `applies_to` | `deployer`, `developer`, `provider`, `employer`, `data_fiduciary`, `importer`, `distributor` | any |
| `topic` | `hiring`, `consumer_decisions`, `genai`, `frontier`, `personal_data`, `health`, `security`, `framework` | all |
| `show` | `library`: laws with statutory requirements. `all`: every law in the imported law matrix. | `library` |
| `sort` | `geography`, `name`, `effective_on` (earliest first), `-effective_on` (latest first). Laws without a date come last. | `geography` |
| `page`, `limit` | See [Pagination](#pagination). | 1, 50 |

Request:

```bash
curl -s "https://<host>/api/public/v1/library/laws?topic=hiring&limit=2" \
  -H "X-API-Key: $FUTRAN_LIBRARY_KEY"
```

```js
const res = await fetch("https://<host>/api/public/v1/library/laws?topic=hiring&limit=2", {
  headers: { "X-API-Key": process.env.FUTRAN_LIBRARY_KEY },
});
const { data, pagination } = await res.json();
```

Response `200`:

```json
{
  "data": [
    {
      "id": "86703c80-1aed-49ff-8c6e-abab96623dda",
      "geography": "California",
      "jurisdiction_code": "US-CA",
      "short_name": "FEHA automated-decision system regulations",
      "label": "CA ADS rules",
      "citation": null,
      "type": "statute",
      "binding": true,
      "status": "in_force",
      "status_label": "In force",
      "effective": "1 Oct 2025",
      "effective_on": "2025-10-01",
      "scope": "Employers and other covered entities, and their agents, that use automated-decision systems in employment decisions in California.",
      "applies_to": ["employer"],
      "topics": ["hiring"],
      "requirement_count": 3,
      "role_count": 1,
      "committee": "",
      "penalty": "Remedies under the Fair Employment and Housing Act",
      "last_change": "No change",
      "verify": false,
      "version_no": 1,
      "region": "us_states",
      "region_label": "United States, states and cities"
    },
    {
      "id": "d0a9ac01-6ca6-4889-844d-13fc686f28b1",
      "geography": "Colorado",
      "jurisdiction_code": "US-CO",
      "short_name": "SB 26-189",
      "label": "Colorado",
      "citation": null,
      "type": "statute",
      "binding": true,
      "status": "enacted_not_in_force",
      "status_label": "Enacted, not yet in force",
      "effective": "1 Jan 2027",
      "effective_on": "2027-01-01",
      "scope": "Developers and deployers of automated decision-making technology (ADMT) used to materially influence a consequential decision about a Colorado consumer: education, employment, financial or lending services, insurance, health care, and essential government services and public benefits.",
      "applies_to": ["developer", "deployer"],
      "topics": ["consumer_decisions", "hiring"],
      "requirement_count": 8,
      "role_count": 5,
      "committee": "Consequential-decision rights",
      "penalty": "A violation is a deceptive trade practice under the Colorado Consumer Protection Act (§6-1-105(1)(uuuu), C.R.S.).",
      "last_change": "No change",
      "verify": true,
      "version_no": 1,
      "region": "us_states",
      "region_label": "United States, states and cities"
    }
  ],
  "pagination": { "page": 1, "limit": 2, "total": 5, "pages": 3, "next_page": 2 }
}
```

Field notes:

- `label` is the short name the app shows; `short_name` is the law's name; `citation` is shown only when it is under 120 characters (as in the app).
- `effective` is the display date ("1 Jan 2027", ", phased" when phased); `effective_on` is the compliance date, or the effective date when there is none.
- `scope` is who the law applies to. When it is empty, show `applies_to`.
- `requirement_count` and `role_count` count the statutory requirements and required roles in the current version; `committee` lists the committees or programs the law requires ("(recommended)" when only recommended).
- `verify: true` means the wording or section numbers still need checking against the final official text. The app shows a "Verify" badge; the website should show the same caution.
- `last_change` is the current version's change summary, or "No change" for a first version.

### GET /laws/{law_id}

One law's full record: the overview, current version (status, dates, scope, enforcement, penalties), scope tests, statutory requirements with citations and source quotes, required roles and committees, approved obligations, sources, version history and the court cases that interpret it. Every law listed by `GET /laws` (with either `show` value) opens here. A law id that has been replaced by a newer row of the same law, or retired from the matrix, is 404; use the ids the list and case records give.

```bash
curl -s "https://<host>/api/public/v1/library/laws/d0a9ac01-6ca6-4889-844d-13fc686f28b1" \
  -H "X-API-Key: $FUTRAN_LIBRARY_KEY"
```

```js
const law = await (await fetch(`https://<host>/api/public/v1/library/laws/${id}`, {
  headers: { "X-API-Key": process.env.FUTRAN_LIBRARY_KEY },
})).json();
```

Response `200` (lists shortened):

```json
{
  "id": "d0a9ac01-6ca6-4889-844d-13fc686f28b1",
  "short_name": "SB 26-189",
  "label": "Colorado",
  "citation": null,
  "type": "statute",
  "binding": true,
  "topics": ["consumer_decisions", "hiring"],
  "region": "us_states",
  "region_label": "United States, states and cities",
  "geography": "Colorado",
  "jurisdiction_code": "US-CO",
  "parent_geography": "United States",
  "version": {
    "id": "3a2579af-c947-40d7-8283-c634af5e9cee",
    "version_no": 1,
    "status": "enacted_not_in_force",
    "status_label": "Enacted, not yet in force",
    "signed_on": "2026-05-14",
    "effective_on": null,
    "compliance_on": "2027-01-01",
    "effective_text": "Signed 14 May 2026; applies to consequential decisions made on or after 1 Jan 2027",
    "scope_text": "Developers and deployers of automated decision-making technology (ADMT) used to materially influence a consequential decision about a Colorado consumer: education, employment, financial or lending services, insurance, health care, and essential government services and public benefits.",
    "applies_to": ["developer", "deployer"],
    "enforcer": "Colorado Attorney General only. No private right of action.",
    "private_right_of_action": false,
    "penalty_text": "A violation is a deceptive trade practice under the Colorado Consumer Protection Act (§6-1-105(1)(uuuu), C.R.S.).",
    "cure_period": "60 days after a notice of violation where a cure is possible; none for knowing or repeated violations; the cure right is repealed on 1 Jan 2030",
    "exemptions_text": "Insurers subject to §10-3-1104.9, C.R.S. are generally deemed compliant; HIPAA-covered entities and FDA-regulated devices are largely excluded (law firm summaries; verify against the signed act)",
    "removed_text": "SB 24-205's duty of reasonable care, risk management program and annual impact assessments",
    "litigation_text": "A legal challenge by xAI is reported as pending (law firm summaries); status not confirmed from court records",
    "main_duty": "Notice before use; explanation within 30 days of an adverse outcome; correction; human review; 3-year records",
    "verify": true,
    "approved_at": "2026-11-20T09:12:44.037110"
  },
  "scope_tests": [
    {
      "order": 1,
      "question_text": "Does the client make decisions about Colorado residents?",
      "answer_type": "yes_no",
      "in_scope_rule": { "equals": "yes", "codes": ["US-CO"] },
      "decisive": true,
      "prefill_from": "client_geographies",
      "note": null
    }
  ],
  "requirements": [
    {
      "id": "8e1b6a01-470c-41bd-871b-86ac255e9847",
      "code": "CO-01",
      "text": "Give deployers documentation: intended and known harmful uses, data categories, known limitations and risks, instructions for use and human review",
      "applies_to": ["developer"],
      "needed_by_stage": "procurement",
      "evidence_text": "Documentation pack received from the vendor",
      "role": "vendor_ai_risk_owner",
      "role_name": "Vendor AI risk owner",
      "ai_types": ["decision"],
      "citation": "§6-1-1702(1), C.R.S. (SB 26-189)",
      "source_quote": "ON AND AFTER JANUARY 1, 2027, A DEVELOPER SHALL MAKE AVAILABLE TO EACH DEPLOYER",
      "source_url": "https://leg.colorado.gov/bill_files/115943/download",
      "verify_flag": true
    }
  ],
  "role_maps": [
    {
      "role": "records_retention_owner",
      "name": "Records retention owner",
      "level": "required",
      "needed_by_stage": "ongoing",
      "basis": "CO-02, CO-03: 3-year records",
      "applies_to": [],
      "requirements": ["CO-02", "CO-03"],
      "verify": false
    }
  ],
  "committees": [
    {
      "committee_type": "consequential_decision_rights",
      "title": "Consequential-decision rights",
      "level": "required",
      "basis": "Colorado SB 26-189 (from 1 Jan 2027)",
      "condition": null,
      "items": ["Notice before use", "Explanation after an adverse outcome; data correction", "Human review or reconsideration"]
    }
  ],
  "obligations": [
    {
      "id": "daab040a-bf1f-46b6-be2c-824ecbe81b9a",
      "regulation_id": "d0a9ac01-6ca6-4889-844d-13fc686f28b1",
      "law": "SB 26-189",
      "text": "Give applicants notice before an AI decision.",
      "actor": "deployer",
      "action": null,
      "condition": null,
      "deadline": null,
      "citation": "SB 26-189 §6-1-1703",
      "quote": null,
      "effective_date": null,
      "control_ids": [],
      "question_ids": [],
      "requirement_ids": [],
      "requirements": [],
      "approved_at": "2026-11-24T15:02:10.391694"
    }
  ],
  "sources": [
    { "id": "820d2b55-a625-4d82-8e1c-fc90ab978fdf", "name": "Colorado AG: ADMT rulemaking", "url": "https://coag.gov/ai/", "kind": "official", "last_read_at": "2026-11-25T02:00:41.036307" }
  ],
  "history": [
    {
      "id": "3a2579af-c947-40d7-8283-c634af5e9cee",
      "version_no": 1,
      "change": "SB 26-189 repeals and re-enacts SB 24-205: program, impact assessments and duty of care removed; notice, explanation, correction and human review kept; applies from 1 Jan 2027.",
      "date": "2026-11-20T09:12:44.037110"
    }
  ],
  "cases": [
    {
      "id": "d678ea25-796c-424e-b82b-8b6601127797",
      "name": "Mobley v. Workday, Inc.",
      "geography": "United States · federal",
      "jurisdiction_id": "652975ed-e4d9-4749-88c0-0b262493ec5a",
      "area": "Hiring discrimination (ADEA, Title VII, ADA)",
      "court": "U.S. District Court, Northern District of California",
      "docket_ref": "3:23-cv-00770",
      "description": "An applicant says AI screening features in Workday's software rejected him because of his age, race and disability.",
      "stage": "discovery",
      "stage_label": "Discovery",
      "stage_note": "Age (ADEA) collective preliminarily certified",
      "last_update_on": "2026-10-30",
      "version": 1,
      "regulation_ids": ["99729181-7aed-461f-90b5-141229a4bcf5"],
      "origin": "seed",
      "updated_at": "2026-11-20T09:12:45.092667"
    }
  ]
}
```

Field notes:

- `version` is the current approved version. `history` lists every version up to it, newest first.
- `scope_tests` are the questions the platform asks at client set-up to decide whether the law applies; a law applies only when every `decisive` question passes.
- `requirements[].needed_by_stage`: `program_setup`, `procurement`, `development`, `go_live`, `ongoing`, `yearly`. `ai_types`: `agent`, `decision`, `embedded`, `genai`, `all`.
- `role_maps[].level`: `required`, `recommended`, or `no_longer_required` (a role the previous version required and this one does not).
- `obligations` are approved obligations only (`actor` is who must act).
- `sources[].kind`: `official` or `secondary`.
- `cases` are the litigation tracker's cases that interpret this law, by name, with the case list fields.

### GET /cases

AI court cases in the litigation tracker. Default order: geography, then case name (the tracker's order).

| Parameter | Values | Default |
|---|---|---|
| `stage` | One stage or a comma list: `filed`, `pleadings`, `discovery`, `stayed`, `trial`, `appeal`, `decided`, `settled`, `dismissed`. Anything else is 422. | all |
| `area` | Exact value from `/meta` `cases.filters.areas` | all |
| `geography` | Exact value from `/meta` `cases.filters.geographies` | all |
| `q` | Text found in the case name, area, court or description. Case-insensitive. | none |
| `sort` | `geography`, `name`, `-last_update_on` (most recently checked first) | `geography` |
| `page`, `limit` | See [Pagination](#pagination). | 1, 50 |

```bash
curl -s "https://<host>/api/public/v1/library/cases?stage=discovery&limit=2" \
  -H "X-API-Key: $FUTRAN_LIBRARY_KEY"
```

```js
const params = new URLSearchParams({ stage: "discovery", limit: "2" });
const cases = await (await fetch(`https://<host>/api/public/v1/library/cases?${params}`, {
  headers: { "X-API-Key": process.env.FUTRAN_LIBRARY_KEY },
})).json();
```

Response `200`:

```json
{
  "data": [
    {
      "id": "d678ea25-796c-424e-b82b-8b6601127797",
      "name": "Mobley v. Workday, Inc.",
      "geography": "United States · federal",
      "jurisdiction_id": "652975ed-e4d9-4749-88c0-0b262493ec5a",
      "area": "Hiring discrimination (ADEA, Title VII, ADA)",
      "court": "U.S. District Court, Northern District of California",
      "docket_ref": "3:23-cv-00770",
      "description": "An applicant says AI screening features in Workday's software rejected him because of his age, race and disability. The claims are brought against the software vendor, not an employer.",
      "stage": "discovery",
      "stage_label": "Discovery",
      "stage_note": "Age (ADEA) collective preliminarily certified",
      "last_update_on": "2026-10-30",
      "version": 1,
      "regulation_ids": ["99729181-7aed-461f-90b5-141229a4bcf5", "51b65216-d97d-4029-a6ae-332e5090a3e9", "9f6b671d-3676-4142-bc33-4b93566b37c3"],
      "origin": "seed",
      "updated_at": "2026-11-20T09:12:45.092667"
    }
  ],
  "pagination": { "page": 1, "limit": 2, "total": 3, "pages": 2, "next_page": 2 }
}
```

Field notes: `last_update_on` is when the case was last checked; `stage_note` qualifies the stage; `version` goes up with each approved edit; `origin` is `manual` (added by the Futran team), `claude` (added from an approved AI refresh) or `seed` (a starter case). `regulation_ids` are the law rows as recorded; for links, use `laws` in the case record, which points each one at the law's current row.

### GET /cases/{case_id}

One case's full record: everything in the list, plus why it matters, the talking points written for clients, sources, the stage timeline and the laws it interprets.

```bash
curl -s "https://<host>/api/public/v1/library/cases/d678ea25-796c-424e-b82b-8b6601127797" \
  -H "X-API-Key: $FUTRAN_LIBRARY_KEY"
```

```js
const c = await (await fetch(`https://<host>/api/public/v1/library/cases/${id}`, {
  headers: { "X-API-Key": process.env.FUTRAN_LIBRARY_KEY },
})).json();
```

Response `200`:

```json
{
  "id": "d678ea25-796c-424e-b82b-8b6601127797",
  "name": "Mobley v. Workday, Inc.",
  "geography": "United States · federal",
  "jurisdiction_id": "652975ed-e4d9-4749-88c0-0b262493ec5a",
  "area": "Hiring discrimination (ADEA, Title VII, ADA)",
  "court": "U.S. District Court, Northern District of California",
  "docket_ref": "3:23-cv-00770",
  "description": "An applicant says AI screening features in Workday's software rejected him because of his age, race and disability. The claims are brought against the software vendor, not an employer.",
  "stage": "discovery",
  "stage_label": "Discovery",
  "stage_note": "Age (ADEA) collective preliminarily certified",
  "last_update_on": "2026-10-30",
  "version": 1,
  "regulation_ids": ["99729181-7aed-461f-90b5-141229a4bcf5", "51b65216-d97d-4029-a6ae-332e5090a3e9", "9f6b671d-3676-4142-bc33-4b93566b37c3"],
  "origin": "seed",
  "updated_at": "2026-11-20T09:12:45.092667",
  "why_matters": "A vendor of an AI screening tool can face discrimination claims alongside the employers that use it.\nAge effects (applicants aged 40 and over) are being litigated, not only race and sex.\nDiscovery covers the vendor's bias-testing and applicant data.",
  "talking_points_client": "List every hiring tool that ranks, scores or filters applicants.\nAsk each vendor for its most recent bias audit, including age.\nKeep a person reviewing automated rejections, and keep the records.",
  "sources": [
    { "title": "Order granting preliminary collective certification, 16 May 2025 (Civil Rights Litigation Clearinghouse)", "url": "https://clearinghouse.net/doc/166151" }
  ],
  "timeline": [
    { "on": "2025-05-16", "stage": "pleadings", "label": "Order granting preliminary certification of the age (ADEA) collective" },
    { "on": "2026-05", "stage": "discovery", "label": "Discovery order on bias-testing data, customer applicant data and EEO-1 records" },
    { "on": "2026-06", "stage": "discovery", "label": "Some FEHA and ADA claims proceed; several newly added claims dismissed" }
  ],
  "laws": [
    { "id": "99729181-7aed-461f-90b5-141229a4bcf5", "short_name": "Title VII, Civil Rights Act of 1964", "label": "Title VII, Civil Rights Act of 1964", "geography": "United States", "jurisdiction_code": "US" },
    { "id": "51b65216-d97d-4029-a6ae-332e5090a3e9", "short_name": "Age Discrimination in Employment Act (ADEA)", "label": "Age Discrimination in Employment Act (ADEA)", "geography": "United States", "jurisdiction_code": "US" }
  ]
}
```

Field notes: `why_matters` and `talking_points_client` hold one point per line (split on `\n`). `timeline[].on` is a date or a month (`2026-05`); the last entry is the current stage. Each `laws[].id` opens with `GET /laws/{law_id}`.

### GET /meta

Filter values for both libraries, record counts and refresh times. Use it to build the website's filter menus and headline tiles.

```bash
curl -s "https://<host>/api/public/v1/library/meta" -H "X-API-Key: $FUTRAN_LIBRARY_KEY"
```

```js
const meta = await (await fetch("https://<host>/api/public/v1/library/meta", {
  headers: { "X-API-Key": process.env.FUTRAN_LIBRARY_KEY },
})).json();
```

Response `200` (option lists shortened):

```json
{
  "laws": {
    "filters": {
      "regions": [{ "value": "us_federal", "label": "United States, federal" }, { "value": "us_states", "label": "United States, states and cities" }],
      "topics": [{ "value": "hiring", "label": "Hiring and employment" }, { "value": "consumer_decisions", "label": "Consumer decisions" }],
      "statuses": [{ "value": "in_force", "label": "In force" }, { "value": "in_force_phased", "label": "In force, phased" }],
      "applies_to": [{ "value": "deployer", "label": "Deployer (uses AI)" }, { "value": "developer", "label": "Developer" }],
      "show": [{ "value": "library", "label": "Laws with requirements" }, { "value": "all", "label": "All laws in the matrix" }],
      "sort": ["geography", "name", "effective_on", "-effective_on"]
    },
    "counts": { "laws": 10, "all_laws": 215, "geographies": 7, "requirements": 60, "upcoming_90_days": 2 },
    "last_refreshed_at": "2026-11-26T02:00:41.391752"
  },
  "cases": {
    "filters": {
      "stages": [{ "value": "filed", "label": "Filed" }, { "value": "pleadings", "label": "Pleadings" }, { "value": "discovery", "label": "Discovery" }],
      "areas": ["Challenge to the Colorado AI Act", "Copyright (training data)", "GDPR Art. 22 (automated decisions)", "Hiring discrimination (ADEA, Title VII, ADA)"],
      "geographies": ["Canada · British Columbia", "European Union", "India", "United States · California", "United States · Colorado", "United States · federal"],
      "sort": ["geography", "name", "-last_update_on"]
    },
    "counts": {
      "cases": 11,
      "by_stage": { "filed": 2, "pleadings": 0, "discovery": 3, "stayed": 1, "trial": 0, "appeal": 0, "decided": 3, "settled": 1, "dismissed": 1 }
    },
    "last_refreshed_at": "2026-11-26T02:14:09.391774"
  }
}
```

Counts match the app's tiles: `laws` is "Laws and rules" (laws with requirements), `all_laws` the laws in the imported matrix, `geographies` "Geographies tracked", `requirements` "Statutory requirements" and `upcoming_90_days` "Effective dates in next 90 days".

## Pagination

`GET /laws` and `GET /cases` are paged with `page` (from 1, up to 10,000) and `limit` (1 to 200, default 50). Every list response has:

```json
"pagination": { "page": 2, "limit": 50, "total": 215, "pages": 5, "next_page": 3 }
```

`next_page` is `null` on the last page. A page past the end returns `"data": []`. To load everything, follow `next_page` until it is `null`; the whole law library is a few pages at `limit=200`.

## Errors

Errors use the platform's error shape:

```json
{ "detail": "This website API key is not valid or has been revoked.", "errors": [] }
```

For 422, `errors` lists the fields: `[{ "field": "limit", "message": "Input should be less than or equal to 200" }]`.

| Status | When | `detail` |
|---|---|---|
| 401 | No key | Send a website API key in the X-API-Key header. |
| 401 | Wrong or revoked key | This website API key is not valid or has been revoked. |
| 403 | The request comes from a browser origin the key does not list | This website API key is not allowed from this origin. |
| 403 | A CORS preflight from an origin no active key lists | This origin is not allowed to call the library API. |
| 404 | Unknown, replaced or retired law; unknown or removed case | Not found. |
| 405 | Any method but GET (and OPTIONS for a CORS preflight), including HEAD | Method Not Allowed |
| 422 | A parameter is out of range, unknown, or not one of the listed values | Some fields need attention. (or the specific message) |
| 429 | The key's rate limit is used up | Too many requests for this website API key. Wait and try again. |
| 429 | More than 30 requests a minute from one address with a missing or wrong key | Too many requests without a valid website API key. Wait a minute and try again. |

Error responses are never cached (`Cache-Control: no-store`).

## Rate limits

Each key has its own limit, set when it is created (default 120 requests a minute, over a sliding 60-second window). Every successful response carries:

```
X-RateLimit-Limit: 120
X-RateLimit-Remaining: 87
```

Over the limit, the API answers 429 with `Retry-After` (seconds until a request is allowed again). Requests answered 304 count toward the limit. Requests with a missing or wrong key are limited to 30 a minute per network address.

The limit is counted in each server process. With the platform on more than one server task, each counts separately, so the effective ceiling is the limit times the number of tasks; the AWS WAF rule below gives one shared ceiling.

## Caching and ETags

Every 200 response carries:

```
Cache-Control: public, max-age=300, stale-while-revalidate=600
ETag: "c371a103cc2cba32e4c7f6edc7204692"
Vary: Origin, X-API-Key, Authorization
X-Library-Last-Refreshed: 2026-11-26T02:00:41.391752
```

- Keep a response for 5 minutes; for 10 minutes after that it may be shown while it is fetched again in the background.
- After that, send the ETag back as `If-None-Match`. If nothing changed, the API answers `304 Not Modified` with no body, and the cached copy is good for another 5 minutes.
- The ETag is a hash of the response body, so it changes exactly when the data changes.
- On the server, each query's response is kept in memory and rebuilt when any law, version, requirement, source, obligation, case or refresh run changes, and at least once a minute.

Example of a revalidating fetch on the website's server:

```js
const cache = new Map(); // url -> { etag, body }

async function library(path) {
  const url = `https://<host>/api/public/v1/library${path}`;
  const hit = cache.get(url);
  const res = await fetch(url, {
    headers: { "X-API-Key": process.env.FUTRAN_LIBRARY_KEY, ...(hit ? { "If-None-Match": hit.etag } : {}) },
  });
  if (res.status === 304 && hit) return hit.body;
  if (!res.ok) throw new Error(`Library API ${res.status}: ${(await res.json()).detail}`);
  const body = await res.json();
  cache.set(url, { etag: res.headers.get("ETag"), body });
  return body;
}
```

Frameworks with built-in data caching (for example Next.js `fetch(url, { next: { revalidate: 300 } })`) can be used instead.

## CORS origins

Browser calls are allowed only from the origins listed on the key.

- A preflight (`OPTIONS` with `Origin` and `Access-Control-Request-Method: GET`) is answered 204 for an origin that some active key lists, with `Access-Control-Allow-Origin: <origin>`, `Access-Control-Allow-Methods: GET, OPTIONS`, `Access-Control-Allow-Headers: X-API-Key, Authorization, If-None-Match, Content-Type` and `Access-Control-Max-Age: 600`. Any other origin gets 403.
- The real request is checked against its own key: from a listed origin it carries `Access-Control-Allow-Origin` and `Access-Control-Expose-Headers: ETag, X-Library-Last-Refreshed, Retry-After, X-RateLimit-Limit, X-RateLimit-Remaining`; from any other origin it is refused with 403.
- A key with no origins refuses every request that carries an `Origin` header, so it works from servers only.
- Credentials (cookies) are never allowed. A 401 (missing or wrong key) carries no CORS headers, so the browser reports it as a network error.

The `Origin` header can be set to anything by a program outside a browser, so origin checks stop other websites from using a browser key in their visitors' browsers; they do not make a key that has been published safe. Treat every key as a secret.

## What is excluded and why

The API serves the app's fields by name; a field the app adds later is not served until it is added deliberately (a test fails until each new field is either served or listed here). These app fields are not served.

### Law library list (`/reg/laws`)

| App field | Why it is not served |
|---|---|
| `pending_count`, and "Change proposed" in Last change | Changes waiting for review in the refresh pipeline are not published. `last_change` gives the current version's change. |
| `reviewer_id` | The Futran staff member assigned to review the law. |
| `review_due_on`, `refresh_every_days`, `watch` | Futran's internal review schedule and watch list. |
| `kpis.pending` | Changes waiting for review. |
| `kpis.shown` | A screen count; use `pagination.total`. |
| `claude_available`, `can_approve`, `can_edit` | The signed-in viewer's permissions and tools. |
| `last_refresh.open`, `last_refresh.alert_status`, `last_refresh.id` | Items waiting for review, who the refresh alert went to, and an internal run id. `/meta` gives `last_refreshed_at`. |

The app's library view lists laws with requirements or with a change waiting for review. The API's `show=library` lists laws with requirements only, so a law never appears because of an unpublished change.

### Law record (`/reg/laws/{law_id}`)

| App field | Why it is not served |
|---|---|
| `pending` | Proposed changes waiting for review, and who proposed them. |
| `used_by_clients` | How many Futran clients the law applies to (client applicability). |
| `used_by_systems` | How many client AI systems are linked to the law (client registers). |
| `version.approved_by` | The name of the Futran staff member who approved the version (`approved_at` is served). |
| `history[].by` | The name of the Futran staff member who approved each version. |
| `roles` | The full role catalogue, used by the editor's pick list. The law's own roles are in `role_maps`. |
| `can_edit`, `can_suggest`, `can_approve` | The signed-in viewer's permissions. |
| Obligations: suggested and unsupported obligations | Waiting for review. Only approved obligations are served. |
| Obligations: `approved_by`, `rejected_reason` | The Futran reviewer's name and review notes. |
| Obligations: `confidence`, `quote_found`, `status` | The AI extraction's own checks, used by reviewers; status is always approved. |
| Related cases: `clients_count`, `systems_count`, `match_summary`, `following` | As for the litigation tracker, below. |

Version history lists versions up to the current approved one.

### Litigation tracker (`/litigation`) and case record (`/litigation/{case_id}`)

| App field | Why it is not served |
|---|---|
| `clients_count`, `systems_count`, `match_summary` | How many Futran clients, and which kinds of client AI, match the case (client matches). |
| `matches` | The Futran clients and AI systems that match the case. |
| `match_rule` | The rule that matches the case to client AI registers (types, vendors and uses). |
| `following` | Whether the signed-in staff member follows the case. |
| `talking_points_futran` | Internal talking points for the Chief Auditor and the sales team. (`talking_points_client`, written to be sent to clients, is served.) |
| `can_edit` | The signed-in viewer's permissions. |
| `filters.clients` and the `client_id` filter | They list Futran clients with matching AI. `client_id` is refused with 422. |
| Opportunities, client briefings, follows and assignments | Sales and staff workflow; no endpoint of this API reads them. |

Cases proposed by the litigation refresh are not in the tracker until a person approves them, so they are not served; nor are proposed updates to a case.

A test (`backend/tests/library/test_confidentiality.py`) seeds a client matched to a case, client applicability, an opportunity with an owner and value, a staff follow, a law reviewer, pending proposals and an unapproved obligation, calls every endpoint, and fails if any client name or id, register system, vendor, user id, email or name, opportunity field, pending proposal or internal note appears in any response.

## For the website team

1. **Get a key.** Ask a Futran Admin for a website key with no allowed origins (a server key). Store it in the site's secrets store or environment as `FUTRAN_LIBRARY_KEY`. Use one key per environment (production, staging) so one can be revoked without the other.
2. **Call from the server or the edge, never from browser JavaScript.** A key in browser JavaScript can be read by anyone who opens the site, and used to call the API until it is revoked. Fetch in server-side rendering, a server route, a build step or an edge function, and send the visitor HTML or your own JSON.
   - Static or incremental builds: fetch `/meta`, all pages of `/laws` and `/cases`, and each record at build time; rebuild every 5 to 15 minutes, or on a schedule.
   - Server-rendered pages: use the revalidating fetch above, or your framework's data cache with a 300-second revalidate.
   - Your own API route (for example `/api/laws` on the website) can proxy the library API with the key added server-side, and cache the results.
3. **If you must call from the browser**, ask for a separate key restricted to your site's origin (for example `https://www.futransolutions.com`) with a low rate limit. Accept that the key is visible in the page; the origin check stops other sites using it from their visitors' browsers, not someone copying it into a script. Revoke and replace it if it is misused.
4. **Build the pages from the data.**
   - Filter menus and tiles from `/meta`.
   - The law list from `/laws`; group by `region_label` for the app's layout. Link each law to its record page by `id`.
   - The law page from `/laws/{id}`: overview from `version`, requirements table, roles from `role_maps`, committees, obligations, sources, history and related cases.
   - The case list from `/cases` and case pages from `/cases/{id}`, linking `laws` to the law pages.
   - Show "Last updated" from `X-Library-Last-Refreshed` or `/meta`.
   - Show the same caution as the app: "Each status, date and count comes from the last approved version; confirm with counsel before relying on it", and a "Verify" mark where `verify` or `verify_flag` is true. For cases: "Check the court record before relying on a stage."
5. **Handle errors.** On 429, wait `Retry-After` seconds and keep serving the cached copy. On 401, alert whoever holds the key (it may have been revoked). On 5xx, serve the cached copy.
6. **Ids are stable** while a law or case exists. When a law is replaced by a new row of the same law (for example after a matrix re-import), its old id gives 404; refresh the list from `/laws` and follow `laws` in case records.

## For the AWS team

No new infrastructure is needed. The API is part of the platform application and ships with it.

1. **Routing.** The ALB already routes `/api/public/v1/*` to the platform service; `/api/public/v1/library/*` is under it. No listener or target-group change.
2. **Database.** One additive migration (`f0ce163adcb2`, table `website_api_keys`) runs with the usual `alembic upgrade head` on deploy. Checked on PostgreSQL 16.
3. **Optional: CloudFront in front of `/api/public/v1/library/*`.** If the website team wants an edge cache:
   - Add a behavior for `/api/public/v1/library/*` to the ALB origin with the allowed-methods set `GET, HEAD, OPTIONS` and `OPTIONS` cached (the API answers GET and preflight OPTIONS; HEAD gets 405).
   - Use a cache policy that honours origin `Cache-Control` (minimum TTL 0, default 300, maximum 900) and puts the `X-API-Key`, `Authorization` and `Origin` headers and all query strings in the cache key. Do not drop the key from the cache key: a cached response keyed on the URL alone would be served to callers without a key, around the rate limit.
   - Use an origin request policy that forwards `If-None-Match`, `X-API-Key`, `Authorization` and `Origin`.
   - Do not add a CloudFront response-headers policy for CORS; the platform sets the CORS headers per key.
4. **WAF rate rule.** The platform's rate limit counts in each server task. Add an AWS WAF rate-based rule on the ALB (or CloudFront) for the path prefix `/api/public/v1/library/`, for example 600 requests per 5 minutes per IP, action block, as a shared ceiling across tasks.
5. **Monitoring.** Watch 401, 403 and 429 counts on `/api/public/v1/library/*` in the ALB access logs. A spike of 401s from one address is someone guessing keys (the platform already limits that to 30 a minute per address).
6. **Nothing else changes.** The library refresh runs on the existing scheduler; this API only reads what it publishes.
