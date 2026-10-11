"""Standalone Ghana jobs refresh, adapted from your working V2 notebook.
Default: 3 listing pages per source; this is not exhaustive Ghana coverage.
Run --check for an offline setup check; --run performs collection.
"""
import argparse, contextlib, html, json, os, sys, time, hashlib, tempfile
from pathlib import Path
from datetime import datetime, timezone
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qs
from urllib.robotparser import RobotFileParser
from plotly.offline import get_plotlyjs


SOURCES = {
    "GhanaCurrentJobs": {
        "base_url": "https://www.ghanacurrentjobs.com",
        "listing_url": "https://www.ghanacurrentjobs.com/",
        "delay": 3
    },
    "JobWeb Ghana": {
        "base_url": "https://jobwebghana.com",
        "listing_url": "https://jobwebghana.com/",
        "delay": 3
    },
    "BusinessGhana": {
        "base_url": "https://www.businessghana.com",
        "listing_url": "https://www.businessghana.com/site/jobs",
        "delay": 10
    }
}

USER_AGENT = "GhanaJobsLearningProject/0.1"

CACHE_HOURS = 6

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})

last_request = {}

blocked_hosts = set()

robots_documents = {}

JOB_PATH_PATTERNS = {
    "GhanaCurrentJobs": r"^/job-vacancy-for-[^/]+/?$",
    "JobWeb Ghana": r"^/jobs/[^/]+/?$",
    "BusinessGhana": r"^/site/jobs/[^/]+/\d+/[^/]+/?$"
}

robots_parsers = {}
pagination_report = []

def clean_text(value):
    return " ".join(str(value).split()) if value else None

def parse_job_date(value):
    """Handle ISO dates, full/short months, and ordinal day numbers."""
    if not value:
        return None

    value = re.sub(
        r"(\d)\s*(st|nd|rd|th)\b",
        r"\1",
        value,
        flags=re.IGNORECASE
    )
    value = clean_text(value.replace(",", ""))

    for date_format in (
        "%Y-%m-%d", "%d %B %Y", "%d %b %Y",
        "%d/%m/%Y", "%d-%m-%Y"
    ):
        try:
            return datetime.strptime(value, date_format).date()
        except ValueError:
            continue

    return None

def deadline_status(deadline, posted=None, conflict=False):
    if conflict or (deadline and posted and deadline < posted):
        return "Unverified — conflicting dates"
    if deadline is None:
        return "Unverified — deadline missing or unreadable"
    if deadline < datetime.now(timezone.utc).date():
        return "Expired by listed deadline"
    return "Within listed deadline — open status unverified"

def labelled_value(lines, label, other_labels):
    """Read a label followed by its value, without consuming another label."""
    normalized_labels = {x.lower().rstrip(":") for x in other_labels}

    for index, line in enumerate(lines):
        if line.lower().rstrip(":").strip() == label.lower():
            if index + 1 < len(lines):
                value = lines[index + 1]
                if value.lower().rstrip(":").strip() not in normalized_labels:
                    return value
            return None

        match = re.match(
            rf"^{re.escape(label)}\s*:\s*(.+)$",
            line,
            flags=re.IGNORECASE
        )
        if match:
            return match.group(1).strip()

    return None

def extract_job_record(link, document):
    source = link["source"]
    page = BeautifulSoup(document["text"], "html.parser")

    for tag in page(["script", "style", "noscript"]):
        tag.decompose()

    lines = [
        clean_text(line)
        for line in page.get_text("\n", strip=True).splitlines()
        if line.strip()
    ]
    page_text = " ".join(lines)
    page_title = page.title.get_text(" ", strip=True) if page.title else ""

    record = {
        "job_title": None,
        "employer": None,
        "location": None,
        "location_detail": None,
        "region": None,
        "street_address": None,
        "employment_type": None,
        "category": None,
        "industry": None,
        "salary_raw": None,
        "date_posted": None,
        "deadline_text": None,
        "application_deadline": None,
        "status": None,
        "source": source,
        "job_url": document["final_url"],
        "collected_at_utc": document["fetched_at_utc"],
        "page_title": page_title
    }

    # Keep the date search away from application forms and related ads.
    main_text = page_text.split("Apply for this Job", 1)[0]
    posted = None

    if source == "GhanaCurrentJobs":
        if "job vacancy for" not in page_title.lower():
            raise ValueError("Expected GhanaCurrentJobs title was not found.")

        title = re.split(
            r"\s+-\s+Current Jobs", page_title, maxsplit=1,
            flags=re.IGNORECASE
        )[0]
        record["job_title"] = re.sub(
            r"^Job Vacancy For\s+", "", title, flags=re.IGNORECASE
        ).strip()

        record["location"] = labelled_value(
            lines,
            "Location",
            ["Location", "How To Apply For The Job", "Closing Date"]
        )

    elif source == "JobWeb Ghana":
        if "Job Description" not in page_text:
            raise ValueError("Expected JobWeb Ghana description was not found.")

        metadata_match = re.search(
            r"Company:\s*(.*?)(?:No views yet|Job Description)",
            page_text,
            flags=re.IGNORECASE
        )
        metadata = (
            "Company: " + metadata_match.group(1)
            if metadata_match else ""
        )
        labels = r"Company|Location|State|Job type|Job category|Salary"

        def metadata_field(label):
            match = re.search(
                rf"{re.escape(label)}:\s*(.*?)"
                rf"(?=\s*(?:{labels}):|$)",
                metadata,
                flags=re.IGNORECASE
            )
            return clean_text(match.group(1)) if match else None

        record["employer"] = metadata_field("Company")
        record["location"] = metadata_field("Location")
        record["employment_type"] = metadata_field("Job type")
        record["category"] = metadata_field("Job category")
        record["salary_raw"] = metadata_field("Salary")

        state = metadata_field("State")
        if state:
            record["location_detail"] = re.sub(
                r"^Jobs in\s+", "", state, flags=re.IGNORECASE
            )

        title = re.sub(
            r"\s*-\s*Jobweb Ghana\s*$", "", page_title,
            flags=re.IGNORECASE
        )
        if record["employer"]:
            title = re.sub(
                rf"\s+at\s+{re.escape(record['employer'])}$",
                "", title, flags=re.IGNORECASE
            )
        record["job_title"] = title.strip()

        # Posting date appeared before the description on inspected pages.
        header_text = page_text.split("Job Description", 1)[0]
        date_match = re.search(
            r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b",
            header_text
        )
        if date_match:
            posted = parse_job_date(date_match.group(1))

    elif source == "BusinessGhana":
        if "Job Category" not in lines or "Job Type" not in lines:
            raise ValueError("Expected BusinessGhana fields were not found.")

        start = lines.index("Job Category")
        end = (
            lines.index("Description", start)
            if "Description" in lines[start:] else len(lines)
        )
        info = lines[start:end]
        labels = [
            "Job Category", "Job Type", "Working Experience",
            "Education Level", "Industry", "Salary Range",
            "Qualifications", "Application Deadline", "Description"
        ]

        record["job_title"] = link["listing_title"]
        for output_name, label in [
            ("employment_type", "Job Type"),
            ("category", "Job Category"),
            ("industry", "Industry"),
            ("salary_raw", "Salary Range"),
            ("deadline_text", "Application Deadline")
        ]:
            record[output_name] = labelled_value(info, label, labels)

        # Dedicated location section: stops when its fields end.
        if "Location Information" in lines:
            position = lines.index("Location Information") + 1
            location_labels = {
                "Location": "location",
                "Region": "region",
                "Street Address": "street_address"
            }
            while position < len(lines) and lines[position] in location_labels:
                label = lines[position]
                position += 1
                if (
                    position < len(lines)
                    and lines[position] not in location_labels
                ):
                    record[location_labels[label]] = lines[position]
                    position += 1

        # Keep a more detailed description location separately.
        description_end = (
            lines.index("Location Information")
            if "Location Information" in lines else len(lines)
        )
        for line in lines[end:description_end]:
            match = re.match(
                r"Job Location\s*:\s*(.+)", line, flags=re.IGNORECASE
            )
            if match:
                record["location_detail"] = match.group(1).strip()
                if not record["location"]:
                    record["location"] = record["location_detail"]
                break

        main_text = " ".join(info)

    else:
        raise ValueError(f"No extractor configured for {source}")

    # Recognize both labels and dates split by HTML formatting.
    date_expression = (
        r"(?:\d{4}-\d{2}-\d{2}|"
        r"\d{1,2}(?:\s*(?:st|nd|rd|th))?\s+"
        r"[A-Za-z]+,?\s+\d{4})"
    )
    matches = re.findall(
        rf"(?:Closing Date|Application Deadline)\s*:?\s*({date_expression})",
        main_text,
        flags=re.IGNORECASE
    )

    raw_dates = list(dict.fromkeys(
        ([record["deadline_text"]] if record["deadline_text"] else []) + matches
    ))
    parsed_dates = {
        parsed for raw in raw_dates
        if (parsed := parse_job_date(raw)) is not None
    }

    conflict = len(parsed_dates) > 1
    deadline = next(iter(parsed_dates)) if len(parsed_dates) == 1 else None

    record["deadline_text"] = " | ".join(raw_dates) or None
    record["application_deadline"] = deadline.isoformat() if deadline else None
    record["date_posted"] = posted.isoformat() if posted else None
    record["status"] = deadline_status(deadline, posted, conflict)

    if not record["job_title"]:
        raise ValueError("No job title was extracted.")

    return record

def clean_optional_text(value):
    """Handle None, NaN, and empty strings safely."""
    if pd.isna(value):
        return None

    text = " ".join(str(value).split())
    return text if text else None

def prepare_dashboard_data(records):
    data = records.copy()

    data = data.sort_values("collected_at_utc").drop_duplicates(
        subset=["source", "job_url"],
        keep="last"
    ).reset_index(drop=True)

    text_columns = [
        "job_title", "employer", "location", "location_detail",
        "region", "employment_type", "category", "industry"
    ]

    for column in text_columns:
        data[column] = data[column].map(clean_optional_text)

    employment_mapping = {
        "full-time": "Full-time",
        "full time": "Full-time",
        "permanent/full time": "Full-time",
        "part-time": "Part-time",
        "part time": "Part-time"
    }

    def standardize_employment(value):
        text = clean_optional_text(value)
        if text is None:
            return None
        return employment_mapping.get(text.lower(), text)

    data["employment_type_raw"] = data["employment_type"]
    data["employment_type"] = data["employment_type"].map(
        standardize_employment
    )

    existing_conflict = (
        data["status"].fillna("").str.contains("conflicting", case=False)
    )

    for column in ["date_posted", "application_deadline"]:
        data[column] = pd.to_datetime(
            data[column], format="%Y-%m-%d", errors="coerce"
        )

    today = pd.Timestamp(datetime.now(timezone.utc).date())
    deadline = data["application_deadline"]
    posted = data["date_posted"]

    conflict = existing_conflict | (
        deadline.notna() & posted.notna() & (deadline < posted)
    )

    data["status"] = "Unverified — deadline missing or unreadable"
    data.loc[deadline >= today, "status"] = (
        "Within listed deadline — open status unverified"
    )
    data.loc[deadline < today, "status"] = "Expired by listed deadline"
    data.loc[conflict, "status"] = "Unverified — conflicting dates"

    def normalize(value):
        text = clean_optional_text(value)
        if text is None:
            return ""
        return re.sub(r"\W+", " ", text.casefold()).strip()

    title_key = data["job_title"].map(normalize).fillna("")
    employer_key = data["employer"].map(normalize).fillna("")

    data["possible_cross_site_duplicate"] = False

    generic_employers = [
        "", "confidential", "not stated", "reputable company",
        "reputable publishing firm", "a reputable company"
    ]

    eligible = title_key.ne("") & ~employer_key.isin(generic_employers)
    duplicate_keys = title_key + "|" + employer_key

    source_counts = data.loc[eligible].groupby(
        duplicate_keys[eligible]
    )["source"].nunique()

    candidate_keys = source_counts[source_counts > 1].index

    data.loc[
        eligible & duplicate_keys.isin(candidate_keys),
        "possible_cross_site_duplicate"
    ] = True

    for column in ["date_posted", "application_deadline"]:
        data[column] = data[column].dt.strftime("%Y-%m-%d")

    return data

def build_dashboard(records, output_folder):
    if records.empty:
        raise ValueError("No records available. Existing dashboard preserved.")

    generated_at = datetime.now(timezone.utc).isoformat()
    payload = records.to_json(orient="records", force_ascii=False)

    # Prevent website text from closing an embedded HTML script.
    payload = payload.replace("<", "\\u003c")
    payload = payload.replace("\u2028", "\\u2028")
    payload = payload.replace("\u2029", "\\u2029")

    template = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ghana Jobs Dashboard</title>
<style>
*{box-sizing:border-box}
body{margin:0;background:#f3f6fa;color:#193047;font-family:Arial,sans-serif}
main{max-width:1400px;margin:auto;padding:28px}
h1{margin:0 0 10px;font-size:32px}
h2{font-size:19px}
p{line-height:1.5}
.note{color:#53667a;font-size:14px}
.panel{background:white;padding:20px;border-radius:14px;
       margin:18px 0;box-shadow:0 3px 16px #132a4310}
.filters,.cards,.charts{display:grid;gap:14px}
.filters{grid-template-columns:repeat(auto-fit,minmax(190px,1fr))}
.cards{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
.charts{grid-template-columns:repeat(auto-fit,minmax(330px,1fr))}
.card{background:#123b50;color:white;border-radius:12px;padding:18px}
.card strong{display:block;font-size:30px;margin-bottom:6px}
label{display:block;font-size:13px;font-weight:bold}
input[type=search],select,button{
  width:100%;padding:11px;border:1px solid #c9d5df;
  border-radius:7px;background:white;color:#193047;margin-top:6px}
button{cursor:pointer;background:#007d70;color:white;border:0;font-weight:bold}
.check{display:flex;align-items:center;gap:8px;margin:18px 0}
.toolbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center}
.toolbar button{width:auto}
.scroll{overflow:auto;max-height:650px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:12px;border-bottom:1px solid #e5ebf0;text-align:left;vertical-align:top}
th{background:#edf3f7;position:sticky;top:0}
td:first-child{min-width:190px}
a{color:#007569;font-weight:bold}
.chart{min-height:330px}
#empty{padding:20px;font-weight:bold}
</style>
<script>__PLOTLY__</script>
</head>
<body>
<main>
<h1>Ghana Jobs Dashboard</h1>
<p class="note">
Collected listings from three sources. This is not a
complete survey of Ghana's job market. A future deadline does not confirm
that applications are still being accepted.
</p>
<p id="timestamps" class="note"></p>

<div class="panel">
<div class="filters">
<label>Search title or employer
<input id="search" type="search" placeholder="e.g. teacher or manager">
</label>
<label>Source<select id="source"></select></label>
<label>Location<select id="location"></select></label>
<label>Category<select id="category"></select></label>
<label>Employment type<select id="employment_type"></select></label>
<label>Status<select id="status"></select></label>
</div>
<label class="check">
<input id="includeExpired" type="checkbox"> Include expired listings
</label>
<div class="toolbar">
<button id="reset">Reset filters</button>
<button id="download">Download filtered CSV</button>
</div>
</div>

<div id="cards" class="cards"></div>

<div class="panel">
<div class="filters">
<label>Compare records by
<select id="chartGroup">
<option value="source">Source</option>
<option value="location">Location</option>
<option value="employer">Employer</option>
<option value="category">Category</option>
<option value="employment_type">Employment type</option>
<option value="status">Status</option>
</select>
</label>
<label>Sort listings
<select id="sort">
<option value="title">Job title</option>
<option value="deadline">Earliest deadline first</option>
<option value="posted">Newest posting first</option>
</select>
</label>
</div>
<div class="charts">
<div id="comparison" class="chart"></div>
<div id="trend" class="chart"></div>
</div>
<p id="coverage" class="note"></p>
</div>

<div class="panel">
<h2>Matching listings</h2>
<p class="note">Possible duplicate flags require review. Records with unknown
employers cannot be reliably matched across websites.</p>
<div id="empty" hidden>No listings match these filters.</div>
<div class="scroll">
<table>
<thead><tr>
<th>Job title</th><th>Employer</th><th>Location</th>
<th>Job type</th><th>Deadline</th><th>Status</th>
<th>Source</th><th>Duplicate review</th><th>Listing</th>
</tr></thead>
<tbody id="rows"></tbody>
</table>
</div>
</div>

<div class="panel">
<h2>Collection coverage</h2>
<p class="note">
These are successful collection timestamps for the loaded records.
Filters and browser refreshes do not download new vacancies.
</p>
<div id="sources"></div>
</div>
</main>

<script id="jobData" type="application/json">__DATA__</script>
<script>
"use strict";

const rawJobs = JSON.parse(document.getElementById("jobData").textContent);
const generatedAt = "__GENERATED__";
const el = id => document.getElementById(id);
const text = value => value == null || value === "" ? "Not stated" : String(value);
const expiredLabel = "Expired by listed deadline";
let filtered = [];

function currentJobs(){
  const today = new Date().toISOString().slice(0,10);
  return rawJobs.map(original => {
    const job = {...original};
    const conflict = String(job.status || "").includes("conflicting")
      || (job.date_posted && job.application_deadline
          && job.application_deadline < job.date_posted);
    if(conflict) job.status = "Unverified — conflicting dates";
    else if(!job.application_deadline)
      job.status = "Unverified — deadline missing or unreadable";
    else if(job.application_deadline < today) job.status = expiredLabel;
    else job.status = "Within listed deadline — open status unverified";
    return job;
  });
}

function populateSelect(id, jobs){
  const select = el(id);
  const previous = select.value;
  const values = [...new Set(jobs.map(job => text(job[id])))].sort();
  select.replaceChildren(new Option("All", ""));
  values.forEach(value => select.add(new Option(value, value)));
  if(values.includes(previous)) select.value = previous;
}

["source","location","category","employment_type","status"]
  .forEach(id => populateSelect(id, currentJobs()));

function card(number, label){
  const box = document.createElement("div");
  box.className = "card";
  const value = document.createElement("strong");
  value.textContent = number;
  box.append(value, document.createTextNode(label));
  return box;
}

function countsBy(jobs, column){
  const result = new Map();
  jobs.forEach(job => {
    const key = text(job[column]);
    result.set(key, (result.get(key) || 0) + 1);
  });
  return [...result.entries()].sort((a,b) => b[1] - a[1]);
}

function render(){
  const jobs = currentJobs();
  populateSelect("status", jobs);
  const query = el("search").value.trim().toLowerCase();

  filtered = jobs.filter(job => {
    if(!el("includeExpired").checked && job.status === expiredLabel) return false;
    for(const field of ["source","location","category","employment_type","status"]){
      if(el(field).value && text(job[field]) !== el(field).value) return false;
    }
    const searchable = [job.job_title, job.employer].filter(Boolean).join(" ").toLowerCase();
    return !query || searchable.includes(query);
  });

  const sorting = el("sort").value;
  filtered.sort((a,b) => {
    if(sorting === "deadline")
      return (a.application_deadline || "9999").localeCompare(b.application_deadline || "9999");
    if(sorting === "posted")
      return (b.date_posted || "").localeCompare(a.date_posted || "");
    return text(a.job_title).localeCompare(text(b.job_title));
  });

  el("cards").replaceChildren(
    card(filtered.length, "Matching records"),
    card(new Set(filtered.map(job => job.source)).size, "Matching sources"),
    card(filtered.filter(job => job.status === expiredLabel).length, "Expired in view"),
    card(filtered.filter(job => !job.application_deadline).length, "No parsed deadline")
  );

  const grouped = countsBy(filtered, el("chartGroup").value);
  const groupLabel = el("chartGroup").selectedOptions[0].text;
  Plotly.react("comparison", [{
    type:"bar",
    x:grouped.map(item => item[1]),
    y:grouped.map(item => item[0]),
    orientation:"h",
    marker:{color:"#008577"}
  }], {
    title:{text:"Records by " + groupLabel},
    margin:{l:160,r:20,t:60,b:40},
    height:Math.max(330, grouped.length * 30 + 100),
    yaxis:{autorange:"reversed",automargin:true},
    xaxis:{title:{text:"Records"},dtick:1}
  }, {responsive:true,displayModeBar:false});

  const dated = filtered.filter(job => job.date_posted);
  const dates = countsBy(dated, "date_posted").sort((a,b) => a[0].localeCompare(b[0]));
  Plotly.react("trend", [{
    type:"bar",
    x:dates.map(item => item[0]),
    y:dates.map(item => item[1]),
    marker:{color:"#5572c7"}
  }], {
    title:{text:"Listings by posting date"},
    margin:{l:45,r:20,t:60,b:60},
    height:330,
    xaxis:{type:"date"},
    yaxis:{dtick:1,title:{text:"Records"}},
    annotations:dated.length ? [] : [{
      text:"No posting dates available for this selection",
      showarrow:false,x:0.5,y:0.5,xref:"paper",yref:"paper"
    }]
  }, {responsive:true,displayModeBar:false});

  el("coverage").textContent =
    dated.length + " of " + filtered.length +
    " matching records have a posting date. Missing categories appear as “Not stated”. " +
    "Locations are source labels and may mix cities, areas, and countries.";

  el("rows").replaceChildren();
  el("empty").hidden = filtered.length !== 0;

  filtered.forEach(job => {
    const row = document.createElement("tr");
    for(const field of [
      "job_title","employer","location","employment_type",
      "application_deadline","status","source"
    ]){
      const cell = document.createElement("td");
      cell.textContent = text(job[field]);
      if(field === "location" && job.location_detail)
        cell.title = String(job.location_detail);
      row.append(cell);
    }
    const duplicate = document.createElement("td");
    duplicate.textContent = job.possible_cross_site_duplicate ? "Review" : "—";
    row.append(duplicate);

    const linkCell = document.createElement("td");
    try{
      const url = new URL(job.job_url);
      if(!["https:","http:"].includes(url.protocol)) throw Error("Invalid link");
      const link = document.createElement("a");
      link.href = url.href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "View listing";
      linkCell.append(link);
    }catch{
      linkCell.textContent = "Unavailable";
    }
    row.append(linkCell);
    el("rows").append(row);
  });
}

const timestamps = rawJobs.map(job => job.collected_at_utc).filter(Boolean).sort();
el("timestamps").textContent =
  "Dashboard generated: " + new Date(generatedAt).toLocaleString() +
  " · Loaded records: " + rawJobs.length;

countsBy(rawJobs, "source").forEach(([source, count]) => {
  const dates = rawJobs.filter(job => job.source === source)
    .map(job => job.collected_at_utc).filter(Boolean).sort();
  const paragraph = document.createElement("p");
  paragraph.textContent = source + ": " + count +
    " records · Latest successful record collection: " +
    (dates.length ? new Date(dates[dates.length-1]).toLocaleString() : "Unknown");
  el("sources").append(paragraph);
});

el("search").addEventListener("input", render);
["source","location","category","employment_type","status",
 "includeExpired","chartGroup","sort"].forEach(id =>
    el(id).addEventListener("change", render)
);

el("reset").addEventListener("click", () => {
  el("search").value = "";
  ["source","location","category","employment_type","status"]
    .forEach(id => el(id).value = "");
  el("includeExpired").checked = false;
  render();
});

el("download").addEventListener("click", () => {
  const columns = [
    "job_title","employer","location","location_detail","employment_type",
    "category","industry","salary_raw","date_posted","application_deadline",
    "status","source","job_url","collected_at_utc"
  ];
  function csvCell(value){
    let content = value == null ? "" : String(value);
    // Prevent spreadsheet programs from interpreting scraped text as formulas.
    if(/^[\s]*[=+\-@]/.test(content) || /^[\t\r\n]/.test(content))
      content = "'" + content;
    return '"' + content.replace(/"/g,'""') + '"';
  }
  const lines = [columns.map(csvCell).join(",")];
  filtered.forEach(job => lines.push(columns.map(key => csvCell(job[key])).join(",")));
  const blob = new Blob(["\ufeff" + lines.join("\r\n")], {type:"text/csv;charset=utf-8"});
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "ghana_jobs_filtered.csv";
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

render();
// Reassess deadline status while the page remains open; no scraping occurs.
setInterval(render, 60000);
</script>
</body>
</html>
"""

    html = template.replace("__DATA__", payload)
    html = html.replace("__GENERATED__", generated_at)
    html = html.replace("__PLOTLY__", get_plotlyjs())

    output_folder.mkdir(parents=True, exist_ok=True)
    dashboard_path = output_folder / "ghana_jobs_dashboard.html"
    temporary_path = dashboard_path.with_suffix(".tmp")
    temporary_path.write_text(html, encoding="utf-8")
    temporary_path.replace(dashboard_path)

    return dashboard_path

def canonical_url(url):
    """Remove fragments and normalize default ports."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    port = parts.port

    if port and not (
        (parts.scheme == "https" and port == 443)
        or (parts.scheme == "http" and port == 80)
    ):
        host = f"{host}:{port}"

    return urlunsplit((
        parts.scheme, host, parts.path or "/", parts.query, ""
    ))

def source_allows_url(source_name, url):
    parts = urlsplit(url)
    expected_host = urlsplit(SOURCES[source_name]["base_url"]).hostname

    if parts.scheme not in ("http", "https"):
        return False

    if parts.hostname != expected_host or parts.username or parts.password or parts.port not in (None, 80, 443):
        return False

    if parts.query:
        # Only allow BusinessGhana's observed pagination parameter.
        if (
            source_name != "BusinessGhana"
            or parts.path.rstrip("/") != "/site/jobs"
        ):
            return False

        query = parse_qs(parts.query, keep_blank_values=True)
        if set(query) != {"page"} or len(query["page"]) != 1:
            return False

        if not query["page"][0].isdigit() or int(query["page"][0]) < 1:
            return False

    parser = robots_parsers.get(source_name)
    return parser is not None and parser.can_fetch(USER_AGENT, url)

def listing_page_number(source_name, url):
    """Recognize only the listing-page routes we inspected."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"

    if source_name == "BusinessGhana":
        if path != "/site/jobs":
            return None
        query = parse_qs(parts.query)
        value = query.get("page", ["1"])[0]
        return int(value) if value.isdigit() else None

    if source_name == "GhanaCurrentJobs":
        if path == "/":
            return 1
        match = re.fullmatch(r"/page/(\d+)", path)

    elif source_name == "JobWeb Ghana":
        if path in ("/", "/jobs"):
            return 1
        match = re.fullmatch(r"/jobs/page/(\d+)", path)

    else:
        return None

    return int(match.group(1)) if match else None

def collect_source_links(source_name, refresh=False, max_pages=3):
    """
    Follow actual next-page links.
    max_pages=None removes the page cap.
    """
    url = SOURCES[source_name]["listing_url"]
    visited = set()
    unique_links = {}
    page_count = 0

    while url:
        url = canonical_url(url)

        if url in visited:
            raise ValueError("Pagination returned a previously visited page.")

        if not source_allows_url(source_name, url):
            raise ValueError(f"Pagination URL is excluded by rules: {url}")

        document = download_source_page(
            source_name, url, refresh=refresh
        )
        page = BeautifulSoup(document["text"], "html.parser")

        visited.add(url)
        page_count += 1
        matched_on_page = 0
        before = len(unique_links)

        for anchor in page.find_all("a", href=True):
            job_url = canonical_url(
                urljoin(document["final_url"], anchor["href"])
            )
            parts = urlsplit(job_url)

            if not re.match(JOB_PATH_PATTERNS[source_name], parts.path):
                continue

            if not source_allows_url(source_name, job_url):
                continue

            title = anchor.get_text(" ", strip=True)
            if not title or title.lower() in {
                "details", "view details", "read more"
            }:
                continue

            matched_on_page += 1
            unique_links.setdefault(job_url, {
                "source": source_name,
                "listing_title": title,
                "job_url": job_url,
                "links_collected_at_utc": document["fetched_at_utc"]
            })

        if matched_on_page == 0:
            raise ValueError(f"No job links found on listing page: {url}")

        current_number = listing_page_number(source_name, url)
        next_url = None

        # Follow a real link to the immediately following page.
        for tag in page.find_all(["a", "link"], href=True):
            candidate = canonical_url(
                urljoin(document["final_url"], tag["href"])
            )

            if urlsplit(candidate).hostname != urlsplit(url).hostname:
                continue

            number = listing_page_number(source_name, candidate)

            if current_number is not None and number == current_number + 1:
                next_url = candidate
                break

        if next_url and not source_allows_url(source_name, next_url):
            stop_reason = "Next page excluded by rules"
        elif next_url and max_pages is not None and page_count >= max_pages:
            stop_reason = "Page limit reached"
        elif next_url:
            stop_reason = "Continue"
        else:
            stop_reason = "No next-page link found"

        pagination_report.append({
            "source": source_name,
            "page": current_number,
            "new_unique_links": len(unique_links) - before,
            "total_unique_links": len(unique_links),
            "result": stop_reason
        })

        print(
            f"{source_name}: page {current_number}, "
            f"{len(unique_links)} unique links so far",
            flush=True
        )

        if stop_reason != "Continue":
            break

        url = next_url

    return list(unique_links.values())


def configure(project):
    global PROJECT_DIR, FOLDERS
    PROJECT_DIR = Path(project).expanduser().resolve()
    FOLDERS = {name: PROJECT_DIR / name for name in ('data', 'cache', 'dashboard', 'logs')}
    for folder in FOLDERS.values():
        folder.mkdir(parents=True, exist_ok=True)


def atomic_text(path, text):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(text, encoding='utf-8')
    temp.replace(path)


def atomic_csv(path, frame):
    temp = path.with_suffix(path.suffix + '.tmp')
    frame.to_csv(temp, index=False, encoding='utf-8-sig')
    temp.replace(path)


@contextlib.contextmanager
def run_lock():
    # OS lock releases even when the process crashes. Prevent overlapping runs.
    handle = (PROJECT_DIR / 'refresh.lock').open('a+b')
    handle.seek(0, 2)
    if handle.tell() == 0:
        handle.write(b'0'); handle.flush()
    handle.seek(0)
    acquired = False
    try:
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except OSError as error:
            raise RuntimeError('Another refresh is running. Wait for it to finish.') from error
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def download_page(url, delay=3, refresh=False, allowed=None):
    """Fresh, spaced requests, checked redirects, and one transient retry."""
    # Scheduled runs deliberately request fresh pages. The original cache files
    # remain available to the teaching notebook but are not freshness evidence.
    original = url
    for redirect_count in range(6):
        if allowed is not None and not allowed(url):
            raise ValueError('Request excluded by source rules: ' + url)
        host = urlsplit(url).netloc
        if host in blocked_hosts:
            raise RuntimeError('Host paused after an access/rate-limit response: ' + host)
        for attempt in range(2):
            wait = max(0, delay - (time.monotonic() - last_request.get(host, float('-inf'))))
            if wait:
                time.sleep(wait)
            try:
                response = session.get(url, timeout=(10, 40), allow_redirects=False)
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 1:
                    raise
                time.sleep(max(delay, 5))
                continue
            finally:
                last_request[host] = time.monotonic()
            if response.status_code in (401, 403, 429):
                blocked_hosts.add(host)
                raise RuntimeError(f'HTTP {response.status_code}; requests paused for {host}')
            if response.status_code in (500, 502, 503, 504) and attempt == 0:
                response.close()
                time.sleep(max(delay, 5))
                continue
            break
        if response.is_redirect:
            url = urljoin(url, response.headers['Location'])
            response.close()
            continue
        response.raise_for_status()
        if not response.text.strip():
            raise ValueError('Empty response: ' + url)
        return {'requested_url': original, 'final_url': response.url,
                'content_type': response.headers.get('Content-Type', ''),
                'fetched_at_utc': datetime.now(timezone.utc).isoformat(),
                'text': response.text, 'from_cache': False}
    raise ValueError('Too many redirects: ' + original)


def download_source_page(source_name, url, refresh=False):
    parser = robots_parsers[source_name]
    delay = max(SOURCES[source_name]['delay'], parser.crawl_delay(USER_AGENT) or 0)
    rate = parser.request_rate(USER_AGENT)
    if rate and rate.requests:
        delay = max(delay, rate.seconds / rate.requests)
    return download_page(url, delay=delay, refresh=True,
                         allowed=lambda candidate: source_allows_url(source_name, candidate))


def read_rules(source):
    settings = SOURCES[source]
    expected = urlsplit(settings['base_url']).netloc
    rules = download_page(settings['base_url'] + '/robots.txt', settings['delay'], True,
                          allowed=lambda u: urlsplit(u).scheme == 'https'
                          and urlsplit(u).netloc == expected)
    if 'text/html' in rules['content_type'].lower() or '<html' in rules['text'][:500].lower():
        raise ValueError('Could not verify robots.txt; source skipped.')
    parser = RobotFileParser()
    parser.parse(rules['text'].splitlines())
    robots_parsers[source] = parser


def merge_records(frames):
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()
    data = pd.concat(frames, ignore_index=True)
    required = {'source', 'job_url', 'job_title', 'collected_at_utc'}
    if not required.issubset(data.columns) or data[list(required)].isna().any().any():
        raise ValueError('Saved records contain missing identity fields; stop to inspect them.')
    data['job_url'] = data['job_url'].map(canonical_url)
    return data.sort_values('collected_at_utc', kind='stable').drop_duplicates(
        ['source', 'job_url'], keep='last').reset_index(drop=True)


def load_records():
    # Import existing notebook snapshots as well as resumable script progress.
    paths = sorted(FOLDERS['data'].glob('job_records_*.csv'))
    paths += [FOLDERS['data'] / 'collection_progress.csv', FOLDERS['data'] / 'jobs_current.csv']
    frames = [pd.read_csv(p) for p in paths if p.exists()]
    if not frames:
        paths = sorted(FOLDERS['data'].glob('dashboard_data_*.csv'))
        if paths:
            frames = [pd.read_csv(paths[-1])]
    return merge_records(frames)


def load_links():
    paths = sorted(FOLDERS['data'].glob('job_links_*.csv'))
    frames = [pd.read_csv(p) for p in paths]
    if not frames:
        return pd.DataFrame(columns=['source', 'job_url', 'listing_title'])
    links = pd.concat(frames, ignore_index=True)
    links['job_url'] = links['job_url'].map(canonical_url)
    return links.drop_duplicates(['source', 'job_url'], keep='last')


def render_with_report(records, report, max_pages):
    prepared = prepare_dashboard_data(records)
    # Build in a temporary folder, then publish only the complete page.
    with tempfile.TemporaryDirectory(dir=FOLDERS['dashboard']) as tmp:
        page = build_dashboard(prepared, Path(tmp))
        content = page.read_text(encoding='utf-8')
        rows = ''.join('<tr>' + ''.join('<td>' + html.escape(str(row.get(k, ''))) + '</td>'
                       for k in ('source', 'result', 'discovered', 'updated', 'failed', 'last_success_utc'))
                       + '</tr>' for row in report['sources'])
        panel = ('<section class="panel"><h2>Collection refresh</h2><p>Last attempt (UTC): '
                 + html.escape(report['attempted_at_utc'])
                 + f'. Discovery checks up to {max_pages} listing pages per source. '
                 'Previously saved links are also checked. This is not complete website coverage.</p>'
                 '<p>Failed requests retain older records. No successful download means no new '
                 'verification. Counts represent listings; possible cross-site duplicates are flagged, '
                 'not merged. Last success means all selected requests for that source completed.</p>'
                 '<div class="scroll"><table><thead><tr><th>Source</th><th>Result</th>'
                 '<th>Discovered links</th><th>Updated</th><th>Failed</th><th>Last success UTC</th>'
                 '</tr></thead><tbody>' + rows + '</tbody></table></div></section>')
        content = content.replace('<div id="sources"></div>', panel + '<div id="sources"></div>')
        atomic_text(FOLDERS['dashboard'] / 'ghana_jobs_dashboard.html', content)
    atomic_csv(FOLDERS['data'] / 'dashboard_current.csv', prepared)


def refresh(max_pages=3):
    blocked_hosts.clear(); robots_parsers.clear(); pagination_report.clear()
    records = load_records()
    saved_links = load_links()
    previous_report_path = FOLDERS['logs'] / 'refresh_latest.json'
    previous = json.loads(previous_report_path.read_text(encoding='utf-8')) if previous_report_path.exists() else {}
    last_success = {r['source']: r.get('last_success_utc', 'Never recorded') for r in previous.get('sources', [])}
    report = {'attempted_at_utc': datetime.now(timezone.utc).isoformat(), 'sources': [], 'errors': []}
    print('Existing records:', len(records), flush=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')
    for source in SOURCES:
        row = {'source': source, 'discovered': 0, 'updated': 0, 'failed': 0,
               'last_success_utc': last_success.get(source, 'Never recorded')}
        def record_error(url, error):
            row['failed'] += 1
            report['errors'].append({'source': source, 'url': url, 'error': str(error)})
            print('  Problem:', str(error)[:180], flush=True)
        print('\nChecking', source, flush=True)
        try:
            read_rules(source)
            fresh = []
            try:
                fresh = collect_source_links(source, refresh=True, max_pages=max_pages)
                row['discovered'] = len(fresh)
            except (requests.RequestException, ValueError, RuntimeError) as error:
                record_error(SOURCES[source]['listing_url'], error)
            if fresh:
                saved_links = pd.concat([saved_links, pd.DataFrame(fresh)], ignore_index=True).drop_duplicates(
                    ['source', 'job_url'], keep='last')
                atomic_csv(FOLDERS['data'] / 'job_links_current.csv', saved_links)
            # Refresh stored jobs even after they move off the discovery pages.
            historical = [] if records.empty else [
                {'source': source, 'job_url': r['job_url'], 'listing_title': r['job_title']}
                for r in records.to_dict('records') if r['source'] == source]
            candidates = historical + saved_links[saved_links['source'] == source].to_dict('records') + fresh
            candidates = list({r['job_url']: r for r in candidates}.values())
            for number, link in enumerate(candidates, 1):
                if urlsplit(link['job_url']).netloc in blocked_hosts:
                    record_error(link['job_url'], f'Skipped {len(candidates)-number+1} remaining requests: host paused')
                    break
                print(f"  {number}/{len(candidates)}: {str(link['listing_title'])[:65]}", flush=True)
                try:
                    document = download_source_page(source, link['job_url'], refresh=True)
                    record = extract_job_record(link, document)
                    records = merge_records([records, pd.DataFrame([record])])
                    # Preserve every successful result if the run is interrupted.
                    atomic_csv(FOLDERS['data'] / 'jobs_current.csv', records)
                    row['updated'] += 1
                except (requests.RequestException, ValueError, RuntimeError) as error:
                    record_error(link['job_url'], error)
        except (requests.RequestException, ValueError, RuntimeError) as error:
            record_error(SOURCES[source]['base_url'] + '/robots.txt', error)
        row['result'] = ('Failed' if not row['updated'] else 'Partial' if row['failed'] else 'Success within selected scope')
        if row['updated'] and not row['failed']:
            row['last_success_utc'] = datetime.now(timezone.utc).isoformat()
        report['sources'].append(row)
    report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    report['pagination'] = pagination_report
    atomic_text(FOLDERS['logs'] / f'refresh_{stamp}.json', json.dumps(report, indent=2, ensure_ascii=False))
    atomic_text(previous_report_path, json.dumps(report, indent=2, ensure_ascii=False))
    if not records.empty:
        render_with_report(records, report, max_pages)
    print('\nREFRESH FINISHED\nStored records:', len(records))
    print(pd.DataFrame(report['sources']).to_string(index=False))
    print('Dashboard:', FOLDERS['dashboard'] / 'ghana_jobs_dashboard.html')
    print('Full error log:', previous_report_path)
    print('Reload the dashboard browser tab to read the rebuilt file.')
    return 2 if any(r['failed'] or not r['updated'] for r in report['sources']) else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true', help='Offline setup check only; does not scrape')
    mode.add_argument('--run', action='store_true', help='Collect and rebuild the dashboard once')
    parser.add_argument('--project-dir', default=str(Path.home() / 'ghana_jobs_dashboard_v2'))
    parser.add_argument('--max-pages', type=int, default=3)
    args = parser.parse_args()
    if args.max_pages < 1:
        parser.error('--max-pages must be positive')
    configure(args.project_dir)
    with run_lock():
        if args.check:
            records = load_records()
            if records.empty:
                raise ValueError('No saved jobs found. Confirm the project folder before running collection.')
            prepared = prepare_dashboard_data(records)
            print('SETUP CHECK PASSED')
            print('Python:', sys.executable)
            print('Project:', PROJECT_DIR)
            print('Saved records:', len(records))
            print('Sources:', ', '.join(sorted(records['source'].unique())))
            print('Dashboard exists:', (FOLDERS['dashboard'] / 'ghana_jobs_dashboard.html').exists())
            print('No website requests made. Dashboard and saved records unchanged.')
            return 0
        return refresh(args.max_pages)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        import traceback
        traceback.print_exc()
        print('Refresh stopped. Successful checkpoints and the last complete dashboard are retained.', file=sys.stderr)
        sys.exit(1)
