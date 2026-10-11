"""Build GitHub Pages from saved data; optionally collect fresh job pages first."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
import refresh_jobs as jobs


def read_report(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def fallback_report(previous, attempted, message):
    last = {r['source']: r.get('last_success_utc', 'Not recorded')
            for r in (previous or {}).get('sources', [])}
    return {'attempted_at_utc': attempted, 'finished_at_utc': datetime.now(timezone.utc).isoformat(),
            'sources': [{'source': source, 'result': message, 'discovered': 0,
                         'updated': 0, 'failed': 1 if attempted != 'Not run on GitHub yet' else 0,
                         'last_success_utc': last.get(source, 'Not recorded')}
                        for source in jobs.SOURCES],
            'errors': [{'error': message}], 'pagination': []}


def publish(project, report, code):
    jobs.configure(project)
    records = jobs.load_records()
    if records.empty:
        raise ValueError('No saved records: refusing to replace the existing website.')
    jobs.render_with_report(records, report, 3)
    page = (jobs.FOLDERS['dashboard'] / 'ghana_jobs_dashboard.html').read_text(encoding='utf-8')
    banner = '''<section class="panel"><h2>Daily Ghana job listings</h2>
<p>Collection is scheduled for 10:00 AM Ghana time (UTC). Starts may be delayed;
collection usually takes about an hour. This is a daily snapshot, not an instant feed.</p>
<p id="new-version" class="note">This page checks for a newer published version every five minutes.</p>
</section>'''
    page = page.replace('<div id="sources"></div>', banner + '<div id="sources"></div>')
    version = datetime.now(timezone.utc).isoformat()
    # Polling downloads only tiny version metadata, never scrapes job sources.
    # Avoid resetting the user's filters: offer an explicit reload instead.
    script = '''<script>
const publishedVersion = VERSION;
async function checkPublishedVersion() {
  try {
    const response = await fetch('./version.json', {cache: 'no-store'});
    if (!response.ok) return;
    const latest = await response.json();
    if (latest.version !== publishedVersion) {
      const target = document.getElementById('new-version');
      target.textContent = 'An updated dashboard is available. ';
      const button = document.createElement('button');
      button.textContent = 'Load updated dashboard';
      button.onclick = () => window.location.reload();
      target.append(button);
    }
  } catch (_) { /* Keep the current page working while offline. */ }
}
if (location.protocol.startsWith('http')) setInterval(checkPublishedVersion, 300000);
</script>'''.replace('VERSION', json.dumps(version))
    page = page.replace('</body>', script + '\n</body>')
    output = Path(project) / '_site'
    output.mkdir(exist_ok=True)
    jobs.atomic_text(output / 'index.html', page)
    jobs.atomic_text(output / 'version.json', json.dumps({'version': version}))
    jobs.atomic_text(output / '.nojekyll', '')
    print(f'Built website with {len(records)} saved listings. Collector result: {code}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collect', action='store_true')
    parser.add_argument('--project-dir', default='.')
    args = parser.parse_args()
    root = Path(args.project_dir).resolve()
    jobs.configure(root)
    report_path = jobs.FOLDERS['logs'] / 'refresh_latest.json'
    previous = read_report(report_path)
    code = 0
    if args.collect:
        started = datetime.now(timezone.utc).isoformat()
        try:
            # A bounded collector leaves time to preserve checkpoints and publish status.
            result = subprocess.run([sys.executable, '-u', str(Path(__file__).with_name('refresh_jobs.py')),
                                     '--run', '--project-dir', str(root), '--max-pages', '3'],
                                    timeout=150 * 60, check=False)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
        report = read_report(report_path)
        if code not in (0, 2) or report is None or report.get('attempted_at_utc', '') < started:
            report = fallback_report(previous, started,
                                     'Interrupted refresh; saved checkpoints retained; totals incomplete')
            jobs.atomic_text(report_path, json.dumps(report, indent=2, ensure_ascii=False))
            if code == 0:
                code = 1
    else:
        report = previous or fallback_report(None, 'Not run on GitHub yet',
                                             'Imported laptop data; cloud refresh not tested')
    publish(root, report, code)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as out:
            out.write(f'collector_code={code}\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as out:
            out.write(f'## Ghana jobs refresh\nCollector exit code: `{code}`. '
                      '0 = success (or build only); 2 = source failures; other = interrupted/error.\n'
                      'The dashboard shows source-level status. Saved records are retained.\n')
    # The workflow publishes preserved records, then signals source failures.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
