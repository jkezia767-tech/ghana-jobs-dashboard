# Ghana jobs dashboard

Daily job-listing dashboard built from real collected data using Python, pandas, Beautiful Soup, and Plotly. This package begins with **316 saved listings** supplied on 11 October 2026: BusinessGhana 219, GhanaCurrentJobs 59, and JobWeb Ghana 38. These are listings, not a confirmed count of unique open vacancies.

## First setup — do these steps in order

1. Keep this package separate from the Windows `ghana_jobs_dashboard_v2` folder. It does not replace your working notebook or Windows collector.
2. In `jkezia767-tech/ghana-jobs-dashboard`, open **Settings → Pages**. Under **Build and deployment → Source**, choose **GitHub Actions**. Do not select a Jekyll template.
3. Return to **Code → Add file → Upload files**. Open the extracted `ghana-jobs-dashboard` folder on your computer and drag its **contents** into the upload area, preserving both `.github/workflows` and `data` folders. Do not upload the ZIP or the enclosing folder as one nested folder.
4. The root should contain `.github`, `.gitignore`, `data`, `cloud_run.py`, `refresh_jobs.py`, `requirements.txt`, `README.md`, and `tests`. The workflow must be at `.github/workflows/dashboard.yml`. If the browser omits that folder, use **Add file → Create new file**, enter `.github/workflows/dashboard.yml` as the filename, and paste the entire supplied YAML file. Commit directly to `main` with the message `Prepare online Ghana jobs dashboard`.
5. Open **Actions → Refresh and publish Ghana jobs**. The first upload publishes the saved data without scraping. Wait for the run to finish; use the Pages URL displayed by the deployment. The expected URL after successful deployment is https://jkezia767-tech.github.io/ghana-jobs-dashboard/ . It is not live merely because you have this package.
6. After the initial site works, select **Run workflow**, check **collect**, choose `main`, and run once. Allow about an hour; the collector has a 150-minute time limit. Read the Collection refresh table on the published site. A cloud source can fail even when it works from your laptop.
7. Only after a successful cloud collection, disable **Ghana Job Daily Refresh** in Windows Task Scheduler to avoid collecting twice daily from two computers. The online and local data files do not automatically sync.

Uploading the workflow enables its daily schedule. Nothing has been registered or published by the preparation of this ZIP alone.

## Schedule, cost, and visibility

GitHub Actions runs collection at **10:00 AM UTC**, also 10:00 AM in Ghana. GitHub can delay or occasionally drop scheduled starts, so this is not an exact-time service. Public-repository schedules may be disabled after 60 days without repository activity. Check Actions periodically.

GitHub Pages supports public repositories on GitHub Free. This workflow uses a standard `ubuntu-latest` hosted runner, whose public-repository compute is free. The small Pages artifact is kept for one day; no custom domain, larger runner, paid add-on, or increased cache allowance is required. Storage quotas still apply. All uploaded code, data, and the saved refresh report are publicly readable.

## How updates work

- **GitHub Actions** executes Python while your laptop is off.
- **GitHub Pages** serves the generated HTML. It does not run Python or scrape sites.
- The workflow commits `data/jobs_current.csv`, `data/job_links_current.csv`, and `logs/refresh_latest.json` to `main`, so the next run starts with preserved data. Repository history stores previous versions.
- A normal code upload publishes saved data only. Manual collection and the daily schedule download new data.
- The webpage checks `version.json` every five minutes and offers a button when a newer published dashboard is available. Clicking it reloads the page and resets filters. Reloading a webpage never starts collection.
- No access tokens or passwords are needed in your files. The workflow uses GitHub's built-in job token.

## Failure handling

Each successful detail-page extraction saves a checkpoint. Failed requests do not delete prior jobs or mark them closed. Partial refreshes publish retained data with source-level status, then mark the Actions run as failed so the problem is visible. A timeout or unexpected collector exit is labelled as interrupted, and available checkpoints are preserved.

If collection, commit, rendering, or deployment cannot complete, the previously published website remains available. A hard runner termination or cancellation can prevent checkpoint upload; in that case the last committed dataset remains the starting point, and that interrupted run's uncommitted updates may be lost. Do not edit the data files during a running workflow: competing edits can cause a rebase conflict, which stops publishing instead of overwriting them.

The per-source 'last success' means all selected requests succeeded. It does not mean every vacancy on that website was collected or is open. The imported laptop data has no bundled refresh report, so the initial cloud page correctly says cloud collection has not been tested.

If the first run fails in Configure Pages, confirm **Settings → Pages → GitHub Actions**, then rerun the workflow. If a site returns 401, 403, or 429, the collector stops requests to that host during the run. Do not bypass those restrictions; inspect the source before adding more requests. No automatic whole-workflow retries are configured.

## Coverage and data limitations

The current discovery scope remains **three listing pages per source**, plus saved candidate links and previously collected jobs. This is not all Ghana websites or all vacancies. Do not increase the cap until pagination and workload have been reviewed. Daily checks of historical URLs may become slower as the dataset grows; incremental refresh is a later improvement.

The original working extraction logic is preserved. Missing fields stay blank. A future deadline does not prove a job is open. Missing/conflicting deadlines remain unverified. Listings with expired parsed deadlines are hidden by default. Source-and-URL duplicates are removed; possible cross-site duplicates are flagged for review, not merged. Employer, salary, and posting-date coverage is incomplete. No sample jobs are included in the public dataset.

## Working locally

For this separate project folder (Python 3.12 recommended):

```sh
python -m pip install -r requirements.txt
python cloud_run.py --project-dir .
```

This builds `_site/index.html` from saved data without making website requests. For a real refresh:

```sh
python cloud_run.py --collect --project-dir .
```

In Jupyter, install dependencies with `%pip install -r requirements.txt`. Your existing teaching notebook remains your local learning environment.

## Validation

The package is tested against the supplied real CSVs for offline rendering and against simulated failures in isolated temporary folders for preservation of previous records and interrupted-run reporting. No synthetic test records are added to the published data. The cloud workflow still needs its first real GitHub run; network access from GitHub has not been verified here.

Run offline checks with `python -m unittest discover -s tests -v`.

## Official references

- [GitHub Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages)
- [Scheduled workflow timing and inactivity limits](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub Actions billing and free standard runners](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
