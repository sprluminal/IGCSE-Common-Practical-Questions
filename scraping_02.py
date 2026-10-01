import re, time, pathlib
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs, urljoin

ROOT = "https://pastpapers.papacambridge.com/"
BASE = "https://pastpapers.papacambridge.com/directories/CAIE/CAIE-pastpapers/upload/"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal study scraper)"}
OUT = pathlib.Path("papers")
DELAY = 1.5
YEARS = range(2018, 2027)

# One entry per subject. Slugs are the last part of the subject-page URL.
SUBJECTS = {
    "chemistry": {"code": "0620", "slug": "igcse-chemistry-0620", "papers": "6[1-3]"},
    "physics":   {"code": "0625", "slug": "igcse-physics-0625",   "papers": "6[1-3]"},
    "biology":   {"code": "0610", "slug": "igcse-biology-0610",   "papers": "6[1-3]"},
}

# Document types to fetch, and folder each one is sorted into
DOC_TYPES = {
    "qp": "question_papers",
    "ms": "mark_schemes",
}

def build_pattern(code, papers):
    types = "|".join(DOC_TYPES)
    return re.compile(rf"^{code}_[smw]\d\d_({types})_{papers}\.pdf$")

def get(url):
    time.sleep(DELAY)
    return BeautifulSoup(requests.get(url, headers=HEADERS, timeout=30).text, "html.parser")

def session_pages(slug):
    subject_url = f"{ROOT}papers/caie/{slug}"
    rx = re.compile(rf"/papers/caie/{re.escape(slug)}-(\d{{4}})-")
    seen = set()
    for a in get(subject_url).find_all("a", href=True):
        full = urljoin(ROOT, a["href"])
        m = rx.search(full)
        if m and int(m.group(1)) in YEARS and full not in seen:
            seen.add(full)
            yield full

def pdf_names(page_url):
    soup = get(page_url)
    found = set()
    for a in soup.select('a[href*="download_file.php"]'):
        qs = parse_qs(urlparse(a["href"]).query)
        if "files" in qs:
            found.add(qs["files"][0].rsplit("/", 1)[-1])
    for a in soup.select('a[href*="viewer/caie/"]'):
        m = re.search(r"-(\d{4})-([smw]\d\d)-([a-z]{2})-(\d\d)-pdf$", a["href"])
        if m:
            found.add("_".join(m.groups()) + ".pdf")
    return found

def destination(subject, name):
    doc_type = name.split("_")[2]            # qp / ms
    folder = OUT / subject / DOC_TYPES[doc_type]
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name

def download(subject, name):
    dest = destination(subject, name)
    if dest.exists():
        return
    time.sleep(DELAY)
    r = requests.get(BASE + name, headers=HEADERS, timeout=60)
    if r.ok and r.content[:4] == b"%PDF":
        dest.write_bytes(r.content)
        print("saved", dest)
    else:
        print("failed", name, r.status_code)

for subject, cfg in SUBJECTS.items():
    pattern = build_pattern(cfg["code"], cfg["papers"])
    for page in session_pages(cfg["slug"]):
        print(f"[{subject}] {page}")
        for name in sorted(pdf_names(page)):
            if pattern.match(name):
                download(subject, name)