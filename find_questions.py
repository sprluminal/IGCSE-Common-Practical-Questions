import re, csv, pathlib

try:
    import pymupdf as fitz
except ImportError:
    import fitz  # older PyMuPDF

PAPERS = pathlib.Path("papers")
OUT_CSV = "matches.csv"
_JUNK_KEYWORDS = re.compile(
    r"papacambridge|do not write in this margin|trace id\s*[:*]|"
    r"licensed for hosting|downloaded from papacambridge|"
    r"re-uploading,\s*mirroring or re-hosting",
    re.I,
)

# Remove only the watermark fragment so the surrounding answer remains intact.
_JUNK_INLINE = re.compile(
    r"trace\s*id\s*[:*]\s*[A-Za-z0-9_-]+",
    re.I,
)
_JUNK_BARCODE = re.compile(r"^\*\s?\d{5,}\s?\*$")
_JUNK_FOOTER = re.compile(
    r"^\d{4}/\d{2}\s+(Question Paper|Mark Scheme)\s+\w+\s+\d{4}(\s*\|\s*Source.*)?$",
    re.I,
)
_JUNK_DFD = re.compile(r"^DFD$", re.I)
_JUNK_COMMAS = re.compile(r"^,(\s*,)*$")



def is_junk_line(ln):
    """True if ln is papacambridge watermark noise rather than real content."""
    if not ln.strip():
        return True

    if _JUNK_KEYWORDS.search(ln):
        return True

    if _JUNK_BARCODE.match(ln):
        return True

    if _JUNK_FOOTER.match(ln):
        return True

    if _JUNK_DFD.match(ln):
        return True

    if _JUNK_COMMAS.match(ln):
        return True
    non_ascii = sum(1 for c in ln if ord(c) > 0x7f)

    if non_ascii / len(ln) > 0.4:
        return True

    return False


IMPROVE = (
    r"(?:increase|improve(?:ment)?|reduce|minimi[sz]e|decrease|eliminate|"
    r"remove|avoid|correct\s+for|account\s+for|allow(?:ance)?\s+for)\w*"
)
QUALITY = (
    r"(?:accuracy|precision|reliability|(?:random|systematic)\s+error|"
    r"percentage\s+error|uncertaint(?:y|ies)|anomal(?:y|ies|ous)|"
    r"parallax|human\s+error|reaction\s+time)"
)
PATTERNS = [
    rf"{IMPROVE}.{{0,80}}\b{QUALITY}",
    rf"\b{QUALITY}\b.{{0,80}}{IMPROVE}",
    r"how.{0,60}(more accurate|more precise|more reliable)",
    r"(more accurate|more precise|more reliable).{0,60}(method|result|measurement|experiment|value|reading)",
    r"suggest.{0,60}(improvement|change|modification).{0,80}(method|experiment|procedure|apparatus|technique)",
    r"(evaluate|comment on|assess).{0,80}(accuracy|precision|reliability)",
    r"sources? of (error|inaccuracy|uncertainty)",
    r"limitations? of (the|this) (method|experiment|procedure|investigation)",
]
RX = re.compile("|".join(f"(?:{p})" for p in PATTERNS), re.I | re.S)
ROMAN = ["i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x"]
SESSIONS = {"m": "Feb/Mar", "s": "May/Jun", "w": "Oct/Nov"}
NOISE = re.compile(r"^(©\s*UCLES|©\s*Cambridge|\[Turn over|BLANK PAGE|\d{4}/\d{2}/\w+/\w+/\d{2}$)", re.I)
STOP = ("Notes for use in", "Permission to reproduce", "To avoid the issue")


# Question-numbering parser 
_TOP_QUESTION = re.compile(r"^(\d{1,2})(?=\s|$)")
_PART = re.compile(r"^\(([a-z]+)\)\s*(.*)$", re.I)


def next_letter(c):
    return "a" if c is None else chr(ord(c) + 1)


def ref(q, letter, roman):
    return f"{q}" + (f"({letter})" if letter else "") + (f"({roman})" if roman else "")


def clean_line(ln):
    ln = re.sub(r"[\x00-\x08\x0b-\x1f\t\xa0\u2009\u202f]", " ", ln)
    ln = _JUNK_INLINE.sub(" ", ln)
    return re.sub(r" +", " ", ln).strip()


def _new_span(q, letter, roman, page, text):
    return {
        "q": q,
        "letter": letter,
        "roman": roman,
        "page": page,
        "text": [text],
    }


def parse_question_paper(path):
    lines = []

    with fitz.open(path) as doc:
        for pno, page in enumerate(doc, start=1):
            if pno == 1:  # cover page
                continue

            page_lines = [clean_line(x) for x in page.get_text().splitlines()]
            page_lines = [x for x in page_lines if x]

            if page_lines and page_lines[0].isdigit():  # printed page number
                page_lines = page_lines[1:]

            page_lines = [x for x in page_lines if not is_junk_line(x)]
            lines += [(pno, x) for x in page_lines if not NOISE.match(x)]

    spans, cur = [], None
    q, letter, roman = 0, None, None

    for page, ln in lines:
        if ln.startswith(STOP):
            cur = None
            continue

        rest = ln
        started_question = False

        # Top-level question number, e.g. "2 [3]".
        m = _TOP_QUESTION.match(rest)
        if m:
            candidate_q = int(m.group(1))

            if q < candidate_q <= min(q + 6, 15):
                q, letter, roman = candidate_q, None, None
                rest = rest[m.end():].lstrip()
                cur = _new_span(q, None, None, page, rest)
                spans.append(cur)
                started_question = True

        # A question part may be either a letter, such as (a), or roman
        # numeral directly under the question, such as (v)
        if q:
            pm = _PART.match(rest)
            if pm:
                label = pm.group(1).lower()
                body = pm.group(2)

                is_roman = label in ROMAN and label != next_letter(letter)

                if is_roman:
                    roman = label
                elif len(label) == 1:
                    letter, roman = label, None
                else:
                    if cur is not None:
                        cur["text"].append(rest)
                    continue

                cur = _new_span(q, letter, roman, page, body)
                spans.append(cur)
                continue

        if started_question:
            continue

        if cur is not None:
            cur["text"].append(rest)

    for s in spans:
        t = " ".join(s["text"])
        t = re.sub(r"\.{3,}", " ", t)
        s["text"] = re.sub(r"\s+", " ", t).strip()

    return spans


# Map question reference to answer text
HEADER = re.compile(r"\d{4}/\d{2}\s+Cambridge.{0,120}?Page\s+\d+\s+of\s+\d+", re.S)
FOOTER = re.compile(r"(PUBLISHED\s*)?©\s*(UCLES|Cambridge University Press\s*&\s*Assessment)\s*\d{4}\s*Page\s*\d+\s*of\s*\d+", re.I)
COLS = re.compile(r"Question\s+Answer(?:\s+Marks)?(?:\s+Guidance)?", re.I)
MARK = re.compile(
    r"§\s*(?P<wq>\d{1,2})(?=\s|$)(?!\s*\()"
    r"|(?<![\w/(\d])(?P<q>\d{1,2})\s*\((?P<p1>[a-z]+)\)"
    r"(?:\s*\((?P<p2>[ivx]+)\))?",
    re.I,
)


def _mark_key(m):
    if m.group("wq"):
        return int(m.group("wq")), None, None

    q = int(m.group("q"))
    p1 = m.group("p1").lower()
    p2 = m.group("p2")

    if p2:
        if len(p1) == 1:
            return q, p1, p2.lower()
        return q, None, None

    if p1 in ROMAN:
        return q, None, p1

    if len(p1) == 1:
        return q, p1, None

    return q, None, None


def parse_mark_scheme(path):
    page_texts = []

    with fitz.open(path) as doc:
        for page in doc:
            page_lines = [clean_line(x) for x in page.get_text().splitlines()]
            page_lines = [x for x in page_lines if x and not is_junk_line(x)]
            page_texts.append(" ".join(page_lines))

    text = " ".join(page_texts)
    text = re.sub(r"\s+", " ", text)
    text = HEADER.sub(" ", text)
    text = FOOTER.sub(" ", text)
    text = COLS.sub(" § ", text)

    marks = list(MARK.finditer(text))
    answers = {}

    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        body = text[m.end():end].replace("§", " ")
        body = re.sub(r"\s+", " ", body).strip()
        key = _mark_key(m)

        answers[key] = (answers[key] + " " + body).strip() if key in answers else body

    return answers


def lookup(answers, q, letter, roman):

    exact = (q, letter, roman)
    if exact in answers:
        return answers[exact]
    aliases = []

    if letter is None and roman in ROMAN:
        aliases.extend([(q, None, roman), (q, roman, None)])
    if roman is None and letter in ROMAN:
        aliases.extend([(q, letter, None), (q, None, letter)])

    for alias in aliases:
        if alias in answers:
            return answers[alias]

    # Compare labels independently of whether extractor stored them as letter or roman component.
    if roman in ROMAN:
        hits = []
        for k, v in answers.items():
            if k[0] != q:
                continue
            labels = [x for x in (k[1], k[2]) if x]
            if roman in [x.lower() for x in labels]:
                hits.append((k, v))
        if len(hits) == 1:
            return hits[0][1]

    # Preserve the previous part-level fallback behaviour.
    hits = [(k, v) for k, v in answers.items() if k[0] == q and k[1] == letter]
    if hits:
        return " | ".join(f"{ref(*k)}: {v}" for k, v in hits)

    # If specific part is unavailable, fall back to whole-question
    # entry when mark scheme represents the question that way
    whole = (q, None, None)
    if whole in answers:
        return answers[whole]

    # For whole-question request, return all question entries rather than
    # an empty string when mark scheme represents them part-by-part
    if letter is None and roman is None:
        hits = [(k, v) for k, v in answers.items() if k[0] == q]
        if hits:
            return " | ".join(f"{ref(*k)}: {v}" for k, v in hits)

    return ""


def find_mark_scheme(qp):
    name = qp.name.replace("_qp_", "_ms_")
    roots = [qp.parent.parent / "mark_schemes", qp.parent]

    # Exact path first, preserving the original lookup behaviour.
    for root in roots:
        cand = root / name
        if cand.exists():
            return cand

    # Case-insensitive filename fallback
    folded = name.casefold()
    for root in roots:
        if not root.exists():
            continue
        for cand in root.glob("*.pdf"):
            if cand.name.casefold() == folded:
                return cand

    return None


# main
rows = []

for qp in sorted(PAPERS.rglob("*_qp_*.pdf")):
    subject = qp.parent.parent.name if qp.parent.name == "question_papers" else ""
    m = re.match(r"(\d{4})_([smw])(\d\d)_qp_(\d\d)", qp.name)
    year = f"20{m.group(3)}" if m else ""
    session = SESSIONS.get(m.group(2), "") if m else ""
    ms_path = find_mark_scheme(qp)
    answers = parse_mark_scheme(ms_path) if ms_path else {}
    spans = parse_question_paper(qp)
    matched_questions = set()

    for s in spans:
        found = [x.group(0) for x in RX.finditer(s["text"])]
        if not found:
            continue

        matched_questions.add(s["q"])
        marks = re.findall(r"\[(\d+)\]", s["text"])
        rows.append([
            subject, qp.name, year, session,
            ref(s["q"], s["letter"], s["roman"]), s["page"],
            marks[-1] if marks else "",
            " / ".join(found),
            s["text"],
            lookup(answers, s["q"], s["letter"], s["roman"]) if answers else "(mark scheme not found)",
        ])

    by_q = {}
    for s in spans:
        by_q.setdefault(s["q"], []).append(s)

    for q, group in by_q.items():
        if q in matched_questions:
            continue

        full = " ".join(s["text"] for s in group)
        found = [x.group(0) for x in RX.finditer(full)]
        if not found:
            continue

        marks = re.findall(r"\[(\d+)\]", full)
        rows.append([
            subject, qp.name, year, session,
            f"{q} (check all parts)", group[0]["page"],
            marks[-1] if marks else "",
            " / ".join(found),
            full,
            "(mark scheme: check part-by-part)",
        ])

with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow([
        "subject", "file", "year", "session", "question", "page",
        "marks", "matched", "question_text", "mark_scheme_answer",
    ])
    w.writerows(rows)

print(f"{len(rows)} matching questions -> {OUT_CSV}")
