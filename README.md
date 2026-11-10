# Ghana jobs dashboard

Python collection and a GitHub Pages dashboard for GhanaCurrentJobs, JobWeb Ghana, BusinessGhana and GLMIS (Ghana Labour Market Information System).

JobSearch Ghana is paused after HTTP 403 responses from GitHub. Its extractor is retained for future review, but it is not in the active source list and receives no requests.

## Installation of the GLMIS update

Upload refresh_jobs.py and README.md from upload_to_github to the repository root on main. The collector MUST be named refresh_jobs.py. The uploaded repository contained refresh_jobs (1).py, which the workflow does not run. A numbered filename does not replace the active collector.

Keep cloud_run.py, requirements.txt, .github/workflows/dashboard.yml, all data files and logs. The separate GLMIS access-check workflow can remain. This package contains no replacement CSVs or refresh report.

After the upload finishes publishing saved records, run Refresh and publish Ghana jobs manually with collect checked. Review the GLMIS row, actual pages checked, new records, failures and timestamps. Future scheduled collections include GLMIS automatically. The first complete GitHub collection still needs verification.

## Collection scope

The three original sources each allow up to 10 listing pages, 200 detail checks and 40 minutes per run. GLMIS runs last and allows up to 3 pages, 50 detail checks and 15 minutes. Total source budgets are 135 minutes, below the existing cloud collector timeout of 150 minutes. A single in-flight request may finish after a source budget expires. Only actual pagination links are followed. This is not complete website coverage.

New links and saved jobs due for rechecking share capacity. Unfinished links remain queued. Recheck eligibility is 20 hours for future/today deadlines; 3 days for missing/conflicting deadlines; 7 days for expired deadlines or unavailable pages; 20 hours after other request failures. A scheduled run checks eligible records within its limits.

Requests are spaced and robots rules are checked every run. GLMIS robots.txt returned 404 in the access check and preparation; only 404/410 missing-rule responses are treated as absent rules for this source (RFC 9309 section 2.3.1.3). Robots rules are not authorization to republish. Authentication, rate-limit, server, and network failures do not get this fallback. A newly published robots policy will be read normally. No logins or application submissions are automated.

## GLMIS data limitations

The extractor uses the public job-detail card for title, employer, full location text, category and employment type. It avoids profile forms and unrelated page content. Relative posting ages such as Posted 4 days ago are not converted into an exact date. Missing salaries/deadlines remain blank; explicitly labelled closing dates can be parsed. The job-detail link is supplied so visitors can review and apply through the source; applying may require a GLMIS account.

GLMIS also carries overseas opportunities. Explicit destination terms in titles/location (including Bulgaria, Europe, Qatar and UAE) are excluded. This is a conservative filter, not a guarantee that every remaining advert is located in Ghana. Ambiguous adverts still require review; employer location can differ from work location.

A collected listing is not proof that a vacancy remains open. Jobs past a parsed deadline are excluded from the default active view; missing or conflicting deadlines remain unverified. Cross-site duplicate candidates are flagged, not merged. Source-and-URL duplicates are removed.

## Updates and failure handling

The existing GitHub workflow schedules collection at 10:00 UTC/Ghana time. Actual starts can be delayed. A normal code upload publishes saved data without collection. Manual collection requires checking collect. Browser refreshes never collect vacancies; the webpage checks for a newer published version and offers reload.

Successful discovery and extraction work is checkpointed. Failed requests preserve earlier records and successful collection timestamps. Unavailable pages do not establish that jobs are closed. Partial results can publish while the workflow flags errors. A hard cancellation may prevent uncommitted checkpoints from reaching GitHub. The workflow commits data/jobs_current.csv, data/job_links_current.csv and logs/refresh_latest.json for subsequent runs.

## Local use

Install packages with python -m pip install -r requirements.txt (in Jupyter use %pip install -r requirements.txt).

Build saved data: python cloud_run.py --project-dir .
Collect and build: python cloud_run.py --collect --project-dir .
Output: _site/index.html.

## Validation — 10 November 2026

The user confirmed a passing GLMIS access check from GitHub. During preparation the actual collector fetched two listing pages and extracted two real detail pages, discovering 17 candidates after explicit overseas-title exclusions. These test records were not inserted into the saved dataset. Nine tests passed for existing offline rendering, data retention on source failure, timeout handling, GLMIS field/date extraction, overseas exclusions, pagination, missing-versus-failed robots requests, paused-source/budget settings, and checkpoint/report integration.

The optional validation/test_glmis.py file can be copied into tests/ alongside test_cloud.py. Run python -m unittest discover -s tests -v. Synthetic fixtures are isolated from real saved data.

## Reviewed sources

- https://www.glmis.gov.gh/Jobs/
- https://www.glmis.gov.gh/JobPostings/JobDetails/5521
- https://www.glmis.gov.gh/PrivacyPolicy
- https://www.glmis.gov.gh/robots.txt
- https://www.rfc-editor.org/rfc/rfc9309.html

No public GLMIS data API or feed was verified. Public HTML is used, without publishing full job descriptions or any applicant/profile information.
