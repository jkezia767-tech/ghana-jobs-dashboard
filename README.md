# Ghana jobs dashboard

A Python collector and static dashboard for GhanaCurrentJobs, JobWeb Ghana and BusinessGhana. The dashboard displays collected listings; it does not establish that every listing is a unique, currently open vacancy.

## Collection scope

Discovery follows actual pagination links for up to 10 listing pages per source. It stops earlier when no valid next link exists, site rules prohibit access, or a request fails. It saves discovered links after each successful listing page. This is not complete coverage of these sites or of Ghanaian vacancies.

Each source has a 40-minute work budget and at most 200 detail-page attempts per run. New links and saved jobs due for rechecking share the queue. Unfinished candidates remain saved for a later run. A backlog can take multiple runs to clear; collection is not real-time.

Rechecks become eligible after:

- 20 hours for listings with a parsed deadline that has not expired.
- 3 days for missing or conflicting deadlines.
- 7 days for expired deadlines or unavailable pages (HTTP 404/410).
- 20 hours after other failed detail-page requests.

The next scheduled run checks eligible jobs within its limits. A future deadline or a successfully retrieved page does not prove that applications remain open. Missing information stays blank. Cross-site duplicate candidates are flagged, not automatically merged.

## Refresh and publishing

The existing GitHub workflow runs scheduled collection at 10:00 UTC (Ghana time). Scheduled starts can be delayed. A normal Python code upload builds and publishes saved data only. For a manual collection, open Actions, select the dashboard workflow, choose Run workflow, select main, and enable the collect input.

GitHub Actions runs Python; GitHub Pages serves the generated HTML. Refreshing the browser does not start a collection. The webpage checks for a newer published version and offers a reload button. The local Windows notebook and the online dataset do not automatically synchronize.

The workflow retains data/jobs_current.csv, data/job_links_current.csv and logs/refresh_latest.json in the repository. The dashboard Collection refresh table reports discovery, updates, unavailable pages, jobs not yet due, queued work, failures and the last successful detail download. A successful workflow can be a build-only run: check the collection timestamp to confirm new collection.

## Failures and retained data

Successful extraction and discovery work is checkpointed. Failed requests retain existing jobs and their original successful collection timestamps; they do not mark jobs closed. HTTP 404/410 means page unavailable and job status unverified. Other request failures are reported as failures. Authentication/rate-limit responses stop further requests to that host for the run. Requests respect robots rules and polite delays.

Partial results can be published with source-level errors. A hard cancellation may prevent uncommitted checkpoints from reaching GitHub. Avoid editing saved data during a running workflow. Repository history retains earlier committed versions.

## Local use

Install dependencies in your environment:

```sh
python -m pip install -r requirements.txt
```

In Jupyter, use `%pip install -r requirements.txt` instead.

Build from saved records without scraping:

```sh
python cloud_run.py --project-dir .
```

Collect, then build:

```sh
python cloud_run.py --collect --project-dir .
```

Output is _site/index.html. The cloud wrapper has a 150-minute collector timeout. The workflow configuration is unchanged by this update.

## Validation

The November 2026 coverage update passed eight offline tests: real-data rendering, source-failure preservation, timeout handling, recheck eligibility, partial pagination retention, pagination limits, queued work across repeated runs, and time-budget retention. Synthetic fixtures are isolated from saved job data. Expanded pagination still requires a live run, especially BusinessGhana, which timed out during the preparation check.

Run repository tests with `python -m unittest discover -s tests -v`. The update ZIP includes additional incremental tests in its validation folder; these can be copied into tests when desired.
