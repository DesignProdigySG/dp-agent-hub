# Data health check: the seven dimensions

Use this when someone asks how healthy the Marketo database is, why a lead scored the way it
did, or what to fix first. The **Full data health scan** task does the measuring; this is how
its numbers are made, so you can explain them and act on them.

Every lead gets a 0–100 score per dimension and a weighted overall score. Database KPIs are
averages and counts over every lead in the scan, not a sample.

| Dimension | What it checks | Score |
|---|---|---|
| Uniqueness | Same person in several records: matching email, full name + phone (last 9 digits, so with or without country code), or full name + company (Inc / Ltd / LLC ignored). | 100 unique; 70 for the best record of a group (merge the rest into it); 0 for a duplicate |
| Completeness | Relevant fields filled (default: first and last name, email, company, title, industry, employees or revenue, country, phone or mobile). Flags empty fields that can be filled from the email domain (company, country from a country domain). | % of relevant fields filled |
| Normalization | Values in the expected form: country and industry on the master list, names in Title Case, email lowercase, phone in +international format, employees a number. | % of checks passed |
| Accuracy | Values that can't be real: invalid or placeholder email (test@, example domains, disposable mailboxes, domains with no DNS), fake names (asdf, Test Test, Mickey Mouse, confirmed by AI review when unsure), impossible phone numbers, placeholder company / title. Invalid data should be blanked, not kept. | % of checks passed |
| Contactability | Channels that work: email (valid, domain exists, not unsubscribed, invalid, suspended, blocklisted or hard-bounced, and deliverable if verified), phone (valid number, not Do Not Call, valid if verified), and whether the only email is a free one. | Email 60 + phone 25 + corporate email 15 |
| Recency | Months since the last activity (or since creation when there is none). | 100 within 3 months, then 80 / 60 / 40 / 20 at 6 / 12 / 18 / 36, 0 beyond |
| Engagement | Opens, clicks (x3), form fills (x5) and web visits over the history window (18 months by default), weighted to recent activity. | 60% recency of last engagement + 40% volume. Hot 60+, warm 30+, cold 1+, dormant 0 |

Default weights: uniqueness 15, completeness 15, normalization 10, accuracy 20,
contactability 20, recency 10, engagement 10. Segmentation guides from the method: accuracy
above 80, engagement above 60, overall above 70 for campaign eligibility.

## Acting on results

- Merging and changing lead data are writes: they need approval. Propose them in batches with
  the lead IDs and the exact change.
- Duplicates: keep the most complete record (then the most recently updated); merge the
  others into it with `rest_merge_leads`.
- Prefer blanking an invalid value to keeping it.
- Look at "Where problems come from" (lead source) and "By year created" before fixing
  records one by one: a form or integration producing junk should be fixed first.
