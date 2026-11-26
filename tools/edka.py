#!/usr/bin/env python3
"""EDKA validator and helper CLI. Works with any agent or person: plain files in, plain text or JSON out.

Read-only (safe to run at any time; they never change a file):
    python edka.py validate <wiki-root> [--json report.json] [--legacy] [--raw-root DIR] [--max N]
    python edka.py stats    <wiki-root> [--legacy]
    python edka.py view     <wiki-root> <topic.md> (--profile NAME | --project ID)      # prints to the screen
    python edka.py answer-check <wiki-root> <answer.md> [--profile NAME | --project ID]

Write files (run them on purpose):
    python edka.py hash       <wiki-root> [--raw-root DIR]    # edits only the sha256 lines in sources.yaml
    python edka.py new-source <wiki-root> --id ID --title T --edition E --raw PATH --pages N [--kind K] [--paraphrase]
                              # appends one entry to sources.yaml; creates sources/<id>/coverage.md
    python edka.py new-topic  <wiki-root> <topics/branch/name.md> --title T --sources id1,id2   # creates one new page
    python edka.py view ... --out FILE                        # writes the view to FILE

Existing text in sources.yaml (comments included) is never rewritten. No command calls a model or the network.
Needs Python 3.9+ and PyYAML; pdftotext is optional (raw-text checks on PDFs).
"""
from __future__ import annotations

import argparse, collections, datetime as dt, hashlib, json, os, re, shutil, subprocess, sys, unicodedata
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("edka: PyYAML is required (pip install pyyaml)")

VER_STATUS = ["unverified", "author-checked", "sample-audit", "independent-partial", "independent", "derived"]
DEPTHS = ["raw", "wiki", "index", "not-opened"]
CONFLICT_STATUS = ["open", "resolved-by-profile", "resolved-by-project", "accepted-difference"]
TREATMENTS = ["transcribed", "summarised", "not-ingested", "no-relevant-content", "pending"]
KINDS = ["normative", "guidance", "client-requirement", "catalogue", "other"]

CODES = {
    "E001": "frontmatter missing or not valid YAML",
    "E002": "required field missing",
    "E003": "unknown source id",
    "E004": "invalid verification status",
    "E005": "broken internal link",
    "E006": "raw file missing",
    "E007": "raw file changed since hash (sha256 mismatch)",
    "E008": "coverage map gap or overlap",
    "E009": "sources_silent entry without source/reason/valid depth",
    "E010": "invalid conflict entry",
    "E011": "conflict resolved-by-profile but no profile makes either source binding",
    "E012": "topic uses a source that edka.yaml excludes from all topics",
    "E018": "topic states applicability (a binding column or a per-profile answer); that belongs to profiles and `edka.py view`",
    "E019": "invalid profile (unknown source, or a source listed twice)",
    "E020": "conflict is resolved-by-project but no project records a decision for it",
    "E021": "invalid project file (unknown profile, topic or conflict; or a decision without decision/basis/date)",
    "W119": "topic table row with no link to a source page (view cannot tell which source it is)",
    "W120": "topic paragraph names a source without a ⟦src:id⟧ tag (view cannot hide it for profiles that exclude it)",
    "E022": "invalid structured value (needs key, numeric value, unit and dir: min|max|info)",
    "E023": "structured value not stated in the page body (the values: list must repeat what the page says)",
    "E024": "project decision is less strict than the binding requirement it overrides",
    "W121": "one value key is used with different units or directions across sources (they cannot be compared)",
    "W118": "under this profile neither side of a resolved-by-profile conflict is binding (project decision needed there)",
    "E013": "independent verification without date/by/ref",
    "E014": "invalid registry entry",
    "E015": "number in a topic not found on any page it is derived from",
    "E016": "verbatim quote not found in the raw source text",
    "E017": "independent verification by the same agent/person as the author",
    "W101": "topic older than a page it is derived from (stale synthesis)",
    "W102": "page marker outside the page's source_pages range",
    "W103": "orphan page (no inbound links)",
    "W104": "source has no coverage map",
    "W105": "weak negative evidence (sources_silent depth is index/not-opened)",
    "W106": "registry entry has no sha256 (run `edka.py hash`)",
    "W107": "topic relies on a withdrawn source",
    "W108": "topic relies on a superseded source",
    "W109": "verification ref path not found",
    "W110": "derived page without derived_from",
    "W111": "coverage treatment not in the EDKA vocabulary",
    "W114": "independent verification without an author, so independence cannot be checked",
    "W115": "verbatim page could not be checked (raw text not available)",
    "W117": "raw text could not be extracted (install pdftotext or check the file)",
    "W116": "number on a source page not found in the raw text of its pages (check the page image; OCR may differ)",
    "I001": "raw file not present (source marked not redistributable); integrity not checked",
    "W112": "legacy coverage map: possible gap/overlap (check by hand)",
    "W200": "legacy unstructured field (string instead of mapping)",
}

FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
MDLINK_RE = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")
FENCE_RE = re.compile(r"```.*?```", re.S)
PMARK_RE = re.compile(r"⟦p\.(\d+)⟧")
RANGE_RE = re.compile(r"^\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*$")
FILE_PAGES_RE = re.compile(r"\((\d+)\s*p\.?\)|\b(\d+)\s*pp\b")


def page_total(m):
    return int(m.group(1) or m.group(2)) if m else None
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".obsidian"}
NO_ORPHAN = {"index", "readme", "log", "agents", "claude", "coverage"}


UNIT_ALIASES = {"lux": "lx", "minutes": "min", "minute": "min", "hours": "h", "hour": "h", "hrs": "h",
                "ohm": "Ω", "ohms": "Ω", "mm2": "mm²", "m2": "m²", "percent": "%"}
NUM_RE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?\s*½?|½)\s*(%|lx|lux|minutes?|min|hours?|hrs|h|Ω|ohms?|kVA|kvar|kW|kV|V|kA|A|Hz|°C|dB\(A\)|dB|mm²|mm2|m²|m2|cd|W|ft-candles?|percent)(?![\w²])")
CALC_MARK = "⟦calc⟧"


def numbers_in(text):
    """Set of normalised 'value unit' strings, e.g. {'4 %', '1.5 h', '11 lx'}. Lines marked ⟦calc⟧ are skipped."""
    out = set()
    for line in text.splitlines():
        if CALC_MARK in line:
            continue
        line = re.sub(r"(\d*)\s?1⁄2", lambda m: (m.group(1) or "") + "½", line)  # 1 1/2 written with U+2044
        for v, u in NUM_RE.findall(line):
            v = v.replace(" ", "").replace(",", ".")
            val = (float(v[:-1] or 0) + 0.5) if v.endswith("½") else float(v)
            u = UNIT_ALIASES.get(u.lower() if u not in ("Ω",) else u, u)
            u = "ft-candle" if u.lower().startswith("ft-candle") else u
            out.add(f"{val:g} {u}")
    return out


TIME_TO_MIN = {"min": 1.0, "h": 60.0}
VALUE_DIRS = ("min", "max", "info")   # min: a minimum requirement (higher is stricter); max: a maximum (lower is stricter)


def norm_unit(u):
    u = str(u).strip()
    if u.lower().startswith("ft-candle"):
        return "ft-candle"
    return u if u == "Ω" else UNIT_ALIASES.get(u.lower(), u)


def base_value(value, unit):
    """Value in a comparable base unit (time in minutes, the rest as written)."""
    u, v = norm_unit(unit), float(value)
    if u in TIME_TO_MIN:
        return v * TIME_TO_MIN[u], "min"
    return v, u


def fmt_value(v):
    return f"{v.get('value'):g} {v.get('unit')}" if isinstance(v.get("value"), (int, float)) else f"{v.get('value')} {v.get('unit')}"


def page_values(w, page):
    fm = w.pages[page]["fm"] or {}
    out = []
    for v in fm.get("values") or []:
        if isinstance(v, dict) and v.get("key") and isinstance(v.get("value"), (int, float)) and v.get("unit") \
                and v.get("dir") in VALUE_DIRS:
            out.append({**v, "sid": fm.get("source"), "page_path": page, "base": base_value(v["value"], v["unit"])})
    return out


def topic_values(w, fm):
    vals = []
    for d in fm.get("derived_from") or []:
        dp = (w.root / d).resolve()
        if dp in w.pages:
            vals += page_values(w, dp)
    by = collections.OrderedDict()
    for v in vals:
        by.setdefault(v["key"], []).append(v)
    return by


def stricter(a, b, direction):
    """True if base value a is stricter than b."""
    return a > b if direction == "min" else a < b


def comparable(vals):
    return len({v["base"][1] for v in vals}) == 1 and len({v["dir"] for v in vals}) == 1 and vals[0]["dir"] != "info"


def strictest(vals):
    best = vals[0]
    for v in vals[1:]:
        if stricter(v["base"][0], best["base"][0], v["dir"]):
            best = v
    return best


def norm_text(s):
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    s = s.replace("–", "-").replace("—", "-").replace("−", "-")
    s = re.sub(r"[*_`|]", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


PAGE_SPLIT_RE = re.compile(r"^=== page (\d+) ===$", re.M)


PROFILE_LISTS = ("binding", "client", "reference", "excluded")


def profile_ids(prof, key):
    out = []
    for e in prof.get(key) or []:
        sid = e.get("source") if isinstance(e, dict) else e
        if sid:
            out.append(str(sid))
    return out


def applicability(prof, sid):
    """('binding', rank) | ('client', rank) | ('reference', None) | ('excluded', None) | ('not-listed', None)"""
    for key in PROFILE_LISTS:
        ids = profile_ids(prof, key)
        if sid in ids:
            return key, (ids.index(sid) if key in ("binding", "client") else None)
    return "not-listed", None


def scope_of(prof, sid):
    for key in ("binding", "client"):
        for e in prof.get(key) or []:
            if isinstance(e, dict) and e.get("source") == sid:
                return e.get("scope", "")
    return ""


def governing(prof, between):
    """Which side of a conflict governs under a profile, and why."""
    excluded = [s for s in between if applicability(prof, s)[0] == "excluded"]
    if len(between) - len(excluded) < 2:
        return "n/a", f"not applicable here: {', '.join(excluded)} excluded by this profile"
    binding = sorted((applicability(prof, s)[1], s) for s in between if applicability(prof, s)[0] == "binding")
    client = [s for s in between if applicability(prof, s)[0] == "client"]
    if binding:
        g = binding[0][1]
        note = f"{g} governs (binding #{binding[0][0] + 1})"
        if client:
            note += f"; client {', '.join(client)} applies where stricter"
        return g, note
    if client:
        return client[0], f"client requirement {client[0]} governs (no binding source on this point)"
    return None, "no binding source under this profile: record a project decision"


APPLICABILITY_RE = re.compile(r"^\|.*\bbinding\b.*\|\s*$|\bunder profile\b", re.I | re.M)


class Report:
    def __init__(self):
        self.items = collections.defaultdict(list)

    def add(self, code, path, msg=""):
        self.items[code].append({"path": str(path), "msg": msg})

    def errors(self):
        return sum(len(v) for k, v in self.items.items() if k.startswith("E"))

    def warnings(self):
        return sum(len(v) for k, v in self.items.items() if k.startswith("W"))


def load_yaml(p: Path, default=None):
    if not p.exists():
        return default
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or default


def as_date(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return v if isinstance(v, dt.date) else v.date()
    if isinstance(v, str):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", v)
        if m:
            return dt.date.fromisoformat(m.group(1))
    return None


def legacy_status(s: str):
    """Map the free-text verification strings used by older wikis to a status."""
    s = s.strip().lower()
    for key, st in [("independent-partial", "independent-partial"), ("independent audit", "independent"),
                    ("independent", "independent"), ("sample audit", "sample-audit"),
                    ("author-checked", "author-checked"), ("derived", "derived"),
                    ("not independently verified", "unverified"), ("unverified", "unverified")]:
        if s.startswith(key):
            return st
    return None


COVER_CELL_RE = re.compile(r"^\s*\d+(?:\s*[-–]\s*\d+)?(?:\s*,\s*\d+(?:\s*[-–]\s*\d+)?)*\s*(?:\((.*)\))?\s*$")
FILE_CELL_RE = re.compile(r"\.(pdf|docx?|xlsx?|txt|md)\b|\(\d+\s*pp?\.?\)", re.I)


def parse_cover_pages(s):
    """Physical pages of one coverage row: '5-8', '1, 3', '11-33 (odd)', '5-8 (to 5.6)'. Returns a set or None."""
    m = COVER_CELL_RE.match(str(s))
    if not m:
        return None
    note = (m.group(1) or "").lower()
    pages = set()
    head = s[: s.index("(")] if m.group(1) is not None else s
    for a, b in re.findall(r"(\d+)(?:\s*[-–]\s*(\d+))?", head):
        a, b = int(a), int(b or a)
        if a > b:
            return None
        rng = range(a, b + 1)
        if "odd" in note:
            rng = [n for n in rng if n % 2]
        elif "even" in note:
            rng = [n for n in rng if not n % 2]
        pages.update(rng)
    return pages or None


def parse_range(s):
    m = RANGE_RE.match(str(s))
    if not m:
        return None
    a = int(m.group(1)); b = int(m.group(2) or a)
    return (a, b) if a <= b else None


class Wiki:
    def __init__(self, root: Path, legacy: bool, raw_root=None):
        self.root = root.resolve()
        self.raw_root = Path(raw_root).resolve() if raw_root else self.root
        self._raw_cache = {}
        self.raw_errors = []
        self.legacy = legacy
        self.cfg = load_yaml(self.root / "edka.yaml", {}) or {}
        self.registry = load_yaml(self.root / self.cfg.get("registry", "sources.yaml"), []) or []
        self.has_registry = bool(self.registry)
        self.sources = {s.get("id"): s for s in self.registry if isinstance(s, dict)}
        self.profiles = []
        self.projects = []
        jdir = self.root / self.cfg.get("projects", "projects")
        if jdir.is_dir():
            for jp in sorted(jdir.glob("*.y*ml")):
                self.projects.append((jp, load_yaml(jp, {}) or {}))
        self.topic_conflicts = {}  # (topic rel path, conflict id) -> status
        pdir = self.root / self.cfg.get("profiles", "profiles")
        if pdir.is_dir():
            for p in sorted(pdir.glob("*.y*ml")):
                self.profiles.append((p, load_yaml(p, {}) or {}))
        self.pages = {}  # Path -> dict(fm, body, raw_text)
        layer_skip = {(self.root / self.cfg.get(k, k)).resolve() for k in ("raw", "evidence")}
        for d, dirs, files in os.walk(self.root):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")
                       and (Path(d) / x).resolve() not in layer_skip]
            for f in files:
                if f.endswith(".md"):
                    p = Path(d) / f
                    txt = p.read_text(encoding="utf-8", errors="replace")
                    m = FM_RE.match(txt)
                    fm, err = None, None
                    if m:
                        try:
                            fm = yaml.safe_load(m.group(1))
                            if not isinstance(fm, dict):
                                fm, err = None, "frontmatter is not a mapping"
                        except yaml.YAMLError as e:
                            err = str(e).splitlines()[0]
                    body = txt[m.end():] if m else txt
                    self.pages[p] = {"fm": fm, "err": err, "has_fm": bool(m), "body": body}
        self.by_stem = collections.defaultdict(list)
        for p in self.pages:
            self.by_stem[p.stem.lower()].append(p)

    def raw_path(self, s):
        return self.raw_root / str((s or {}).get("raw", ""))

    def raw_text(self, sid, pages=None, normalise=True):
        """Normalised text of a source's raw file, limited to `pages` (a set) when the format allows."""
        s = self.sources.get(sid)
        if not s:
            return None
        rp = self.raw_path(s)
        if not rp.is_file():
            return None
        key = (sid, tuple(sorted(pages)) if pages else None, normalise)
        if key in self._raw_cache:
            return self._raw_cache[key]
        txt = None
        if rp.suffix.lower() in (".md", ".txt"):
            raw = rp.read_text(encoding="utf-8", errors="replace")
            parts = PAGE_SPLIT_RE.split(raw)
            if pages and len(parts) > 1:
                txt = " ".join(parts[i + 1] for i in range(1, len(parts) - 1, 2) if int(parts[i]) in pages)
            else:
                txt = raw
        elif rp.suffix.lower() == ".pdf":
            exe = os.environ.get("EDKA_PDFTOTEXT") or shutil.which("pdftotext")
            if exe:
                args = [exe, "-enc", "UTF-8"]
                if pages:
                    args += ["-f", str(min(pages)), "-l", str(max(pages))]
                # Some pdftotext builds cannot open non-ASCII paths on Windows: run it from the file's
                # folder with a relative name, or from a temporary ASCII copy if the name itself is not ASCII.
                tmp = None
                if rp.name.isascii():
                    cwd, name = str(rp.parent), rp.name
                else:
                    import tempfile
                    tmp = tempfile.mkdtemp(prefix="edka-")
                    shutil.copy2(rp, Path(tmp) / "src.pdf")
                    cwd, name = tmp, "src.pdf"
                try:
                    res = subprocess.run(args + [name, "-"], capture_output=True, cwd=cwd)
                finally:
                    if tmp:
                        shutil.rmtree(tmp, ignore_errors=True)
                if res.returncode == 0:
                    txt = res.stdout.decode("utf-8", errors="replace")
                else:
                    self.raw_errors.append(f"{sid}: pdftotext failed ({res.stderr.decode(errors='replace')[:80].strip()})")
        if txt is not None:
            txt = norm_text(txt) if normalise else re.sub(r"\s+", " ", txt)
        self._raw_cache[key] = txt
        return self._raw_cache[key]

    def rel(self, p: Path):
        try:
            return p.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(p)

    def page_type(self, p: Path, fm: dict):
        t = (fm or {}).get("type")
        if t:
            return t
        rp = self.rel(p).lower()
        if "coverage" in p.stem.lower():
            return "coverage"
        if p.stem.lower() in ("index", "readme", "log") or p.stem.lower().endswith("-index"):
            return "index"
        if rp.startswith(("topics/", "wiki/topics/")) or "/topics/" in rp:
            return "topic"
        return "source-page"


def check_registry(w: Wiki, r: Report):
    for s in w.registry:
        if not isinstance(s, dict) or not s.get("id"):
            r.add("E014", "sources.yaml", f"entry without id: {s!r:.80}")
            continue
        sid = s["id"]
        for k in ("title", "edition", "kind", "raw", "transcription", "folder", "status"):
            if k not in s:
                r.add("E014", "sources.yaml", f"{sid}: missing '{k}'")
        if s.get("kind") and s["kind"] not in KINDS:
            r.add("E014", "sources.yaml", f"{sid}: kind '{s['kind']}' not in {KINDS}")
        if s.get("transcription") not in (None, "verbatim", "paraphrase"):
            r.add("E014", "sources.yaml", f"{sid}: transcription must be verbatim|paraphrase")
        if s.get("status") not in (None, "active", "superseded", "withdrawn"):
            r.add("E014", "sources.yaml", f"{sid}: bad status '{s.get('status')}'")
        if s.get("supersedes") and s["supersedes"] not in w.sources:
            r.add("E003", "sources.yaml", f"{sid}: supersedes unknown source '{s['supersedes']}'")
        raw = w.raw_path(s)
        if s.get("raw") and not raw.exists() and s.get("redistributable") is False:
            r.add("I001", "sources.yaml", f"{sid}: {s.get('raw')} (pass --raw-root to check a local copy)")
        elif not s.get("raw") or not raw.exists():
            r.add("E006", "sources.yaml", f"{sid}: {s.get('raw')}")
        elif not s.get("sha256"):
            r.add("W106", "sources.yaml", sid)
        elif sha256(raw) != s["sha256"]:
            r.add("E007", "sources.yaml", f"{sid}: {s['raw']} changed; re-verify pages of this source")
        folder = w.root / str(s.get("folder", ""))
        if s.get("folder") and not list(folder.glob("*coverage*.md")):
            r.add("W104", s.get("folder"), sid)


def check_verification(w: Wiki, p: Path, fm: dict, ptype: str, r: Report):
    v = fm.get("verification")
    rp = w.rel(p)
    if v is None:
        if ptype in ("source-page", "topic"):
            r.add("E002", rp, "verification")
        return None
    if isinstance(v, str):
        st = legacy_status(v)
        if not w.legacy:
            r.add("W200", rp, "verification is a string")
        if st is None:
            r.add("E004", rp, v[:70])
        ref = fm.get("verification_ref")
        if ref and w.legacy:
            path = str(ref).split(" ")[0].strip("`\"'").rstrip(";,.)")
            path = re.split(r"(?<=\w)\.\.\d", path)[0]  # "dv-1..5/report.json" names a range of folders
            if not (w.root / path).exists() and not (w.root.parent / path).exists()                     and not list((w.root.parent / path).parent.glob(Path(path).name + "*")):
                r.add("W109", rp, path)
        return st
    if not isinstance(v, dict):
        r.add("E004", rp, repr(v)[:70]); return None
    st = v.get("status")
    if st not in VER_STATUS:
        r.add("E004", rp, str(st)); return None
    if st in ("independent", "independent-partial") and not all(v.get(k) for k in ("date", "by", "ref")):
        r.add("E013", rp, st)
    if st in ("independent", "independent-partial"):
        author = v.get("author") or fm.get("author")
        if not author:
            r.add("W114", rp)
        elif v.get("by") and str(author).strip().lower() == str(v["by"]).strip().lower():
            r.add("E017", rp, f"author = by = {author}")
    if st in ("sample-audit", "author-checked") and not v.get("date"):
        r.add("E002", rp, f"verification.date for {st}")
    if v.get("ref") and not (w.root / str(v["ref"])).exists():
        r.add("W109", rp, str(v["ref"]))
    if st == "derived" and not fm.get("derived_from"):
        r.add("W110", rp)
    return st


def check_source_page(w: Wiki, p: Path, fm: dict, body: str, r: Report):
    rp = w.rel(p)
    if w.has_registry:
        for k in ("source", "source_pages"):
            if k not in fm:
                r.add("E002", rp, k)
        sid = fm.get("source")
        if sid and sid not in w.sources:
            r.add("E003", rp, sid)
    elif "source_pages" not in fm and not str(fm.get("verification", "")).lower().startswith("derived"):
        r.add("E002", rp, "source_pages")
    rng = parse_range(fm.get("source_pages", ""))
    sid = fm.get("source")
    mode = fm.get("transcription") or (w.sources.get(sid) or {}).get("transcription")
    if mode == "verbatim" and w.has_registry and not w.legacy:
        check_verbatim(w, rp, sid, rng, body, r)
    if w.has_registry and not w.legacy and rng:
        raw = w.raw_text(sid, set(range(rng[0], rng[1] + 1)), normalise=False)
        if raw is not None:
            for n in sorted(numbers_in(body) - numbers_in(raw)):
                r.add("W116", rp, f"{n} not in raw pages {rng[0]}-{rng[1]}")
    if fm.get("values") is not None:
        stated = numbers_in(body)
        for v in fm.get("values") or []:
            if not (isinstance(v, dict) and v.get("key") and isinstance(v.get("value"), (int, float))
                    and v.get("unit") and v.get("dir") in VALUE_DIRS):
                r.add("E022", rp, json.dumps(v, ensure_ascii=False, default=str)[:90]); continue
            if f"{float(v['value']):g} {norm_unit(v['unit'])}" not in stated:
                r.add("E023", rp, f"{v['key']} = {fmt_value(v)}")
            if rng and v.get("page") and not rng[0] <= int(v["page"]) <= rng[1]:
                r.add("W102", rp, f"value {v['key']} page {v['page']} not in {rng[0]}-{rng[1]}")
    if rng:
        for n in PMARK_RE.findall(body):
            if not rng[0] <= int(n) <= rng[1]:
                r.add("W102", rp, f"⟦p.{n}⟧ not in {rng[0]}-{rng[1]}")


def blockquotes(body):
    """Paragraphs written as Markdown blockquotes (consecutive '>' lines, blank '>' lines split them)."""
    paras, cur = [], []
    for line in body.splitlines() + [""]:
        s = line.strip()
        if s.startswith(">") and s.lstrip("> ").strip():
            cur.append(s.lstrip(">").strip())
        else:
            if cur:
                paras.append(" ".join(cur)); cur = []
    return paras


def check_verbatim(w, rp, sid, rng, body, r):
    pages = set(range(rng[0], rng[1] + 1)) if rng else None
    raw = w.raw_text(sid, pages)
    quotes = blockquotes(body)
    if not quotes:
        return
    if raw is None:
        r.add("W115", rp, f"{sid}: raw text not available")
        return
    for q in quotes:
        for frag in re.split(r"…|\.\.\.", q):
            f = norm_text(frag)
            if len(f) >= 12 and f not in raw:
                r.add("E016", rp, f'"{frag.strip()[:70]}"')


def source_ids(entries):
    out = []
    for e in entries or []:
        if isinstance(e, dict) and e.get("source"):
            out.append(e["source"])
    return out


def check_topic(w: Wiki, p: Path, fm: dict, r: Report, body: str = ""):
    rp = w.rel(p)
    if not w.legacy and body:
        m = APPLICABILITY_RE.search(FENCE_RE.sub("", body))
        if m:
            r.add("E018", rp, m.group(0).strip()[:70])
        names = {}
        for sid, s in w.sources.items():
            for n in [sid] + ([s["short"]] if isinstance(s.get("short"), str) else list(s.get("short") or [])):
                names[n.lower()] = sid
        for kind, blk in body_blocks(body.splitlines()):
            if kind == "table" and len(blk) >= 2 and set(blk[1].strip()) <= set("|-: "):
                for row in blk[2:]:
                    if not row_sources(w, p, row):
                        r.add("W119", rp, row.strip()[:60])
            elif kind == "para":
                text = "\n".join(blk)
                if blk[0].lstrip().startswith("#"):
                    continue
                tagged = {x.strip() for m in SRC_TAG_RE.findall(text) for x in m.split(",")}
                low = text.lower()
                named = {sid for n, sid in names.items() if re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", low)}
                missing = sorted(named - tagged)
                if missing:
                    r.add("W120", rp, f"{', '.join(missing)}: \"{blk[0].strip()[:50]}\"")
    cov, sil = fm.get("sources_covered"), fm.get("sources_silent")
    if cov is None:
        r.add("E002", rp, "sources_covered")
    if sil is None:
        r.add("E002", rp, "sources_silent (use [] if every source covers the topic)")
    for name, val in (("sources_covered", cov), ("sources_silent", sil)):
        for e in val or []:
            if isinstance(e, str):
                if not w.legacy:
                    r.add("W200", rp, f"{name}: string entry")
                continue
            if not isinstance(e, dict):
                continue
            if w.has_registry and e.get("source") and e["source"] not in w.sources:
                r.add("E003", rp, f"{name}: {e['source']}")
            if name == "sources_silent":
                if not e.get("source") or not e.get("reason") or e.get("depth") not in DEPTHS:
                    r.add("E009", rp, json.dumps(e, ensure_ascii=False)[:100])
                elif e["depth"] in ("index", "not-opened"):
                    r.add("W105", rp, f"{e['source']} ({e['depth']})")
            elif e.get("depth") and e["depth"] not in DEPTHS:
                r.add("E009", rp, f"sources_covered depth '{e['depth']}'")
    used = set(source_ids(cov))
    for sid in used:
        st = (w.sources.get(sid) or {}).get("status")
        if st == "withdrawn":
            r.add("W107", rp, sid)
        elif st == "superseded":
            r.add("W108", rp, sid)
    for sid in sorted(used & set(w.cfg.get("excluded_from_topics") or [])):
        r.add("E012", rp, sid)
    for c in fm.get("conflicts") or []:
        if not isinstance(c, dict) or not c.get("id") or c.get("status") not in CONFLICT_STATUS \
                or not isinstance(c.get("between"), list) or len(c["between"]) < 2:
            r.add("E010", rp, json.dumps(c, ensure_ascii=False, default=str)[:100]); continue
        w.topic_conflicts[(rp, c["id"])] = c["status"]
        if c["status"] == "resolved-by-profile":
            per = {prof.get("name", pp.stem): governing(prof, c["between"])[0] for pp, prof in w.profiles}
            if not any(per.values()):
                r.add("E011", rp, c["id"])
            for name, g in per.items():
                if g is None:
                    r.add("W118", rp, f"{c['id']} under '{name}'")
    # stale synthesis
    tdate = as_date(fm.get("updated"))
    for d in fm.get("derived_from") or []:
        dp = (w.root / d).resolve()
        if dp not in w.pages:
            r.add("E005", rp, f"derived_from: {d}")
            continue
        ddate = as_date((w.pages[dp]["fm"] or {}).get("updated"))
        if tdate and ddate and ddate > tdate:
            r.add("W101", rp, f"{d} updated {ddate} > topic {tdate}")
    for key, vals in topic_values(w, fm).items():
        if len(vals) > 1 and not comparable(vals) and any(v["dir"] != "info" for v in vals):
            r.add("W121", rp, f"{key}: " + ", ".join(f"{v['sid']} {fmt_value(v)} ({v['dir']})" for v in vals))
    derived = [(w.root / d).resolve() for d in fm.get("derived_from") or []]
    derived = [d for d in derived if d in w.pages]
    if derived and body:
        known = set().union(*(numbers_in(w.pages[d]["body"]) for d in derived))
        for n in sorted(numbers_in(body) - known):
            r.add("E015", rp, f"{n} (add the source page to derived_from, or mark a computed line with {CALC_MARK})")


def check_coverage(w: Wiki, p: Path, fm: dict, body: str, r: Report):
    rp = w.rel(p)
    groups = collections.OrderedDict()  # file -> {"total":N, "ranges":[(a,b,treatment)]}
    sid = (fm or {}).get("source")
    default_total = (w.sources.get(sid) or {}).get("pages")
    if default_total is None:
        for s in w.sources.values():
            if s.get("folder") and (w.root / s["folder"]).resolve() == p.parent.resolve():
                default_total = s.get("pages"); break
    current = "main"
    groups[current] = {"total": default_total, "rows": []}
    lines = [l.strip() for l in body.splitlines()]
    is_sep = lambda s: s.startswith("|") and set(s) <= set("|-: ")
    page_col = None  # column holding physical pages in the current table; None = not a coverage table
    for i, s in enumerate(lines):
        if s.startswith("#"):  # every heading starts a new part (e.g. "## Part 2 — x.pdf (30 pp)")
            m = FILE_PAGES_RE.search(s)
            current = s.lstrip("# ")[:70]
            groups.setdefault(current, {"total": page_total(m), "rows": []})
            continue
        if not s.startswith("|") or is_sep(s):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        starts_table = i == 0 or not lines[i - 1].startswith("|")
        if starts_table and i + 1 < len(lines) and is_sep(lines[i + 1]):
            # header row: only tables with a "page(s)" column are coverage tables
            page_col = next((k for k, c in enumerate(cells[:3]) if re.search(r"\bpages?\b", c, re.I)), None)
            continue
        if page_col is None or page_col >= len(cells):
            continue
        idx = page_col if parse_cover_pages(cells[page_col]) else None
        if idx is None:
            continue
        if idx > 0 and cells[0] and FILE_CELL_RE.search(cells[0]):
            current = cells[0]
            m = FILE_PAGES_RE.search(cells[0])
            groups.setdefault(current, {"total": page_total(m), "rows": []})
        treat = cells[-1]
        groups.setdefault(current, {"total": None, "rows": []})["rows"].append(parse_cover_pages(cells[idx]))
        head = re.split(r"[:\s(]", treat.strip("*`").lower(), 1)[0]
        if not w.legacy and head not in TREATMENTS:
            r.add("W111", rp, treat[:50])
    for g, info in groups.items():
        rows = info["rows"]
        if not rows:
            continue
        where = collections.defaultdict(list)  # page -> [(row, is_endpoint)]
        for i, pages in enumerate(rows):
            lo, hi = min(pages), max(pages)
            for n in pages:
                where[n].append(n in (lo, hi))
        # A page may be shared by two rows when it is an end page of each
        # (a clause split mid-page). Anything else listed twice is an overlap.
        dup = sorted(n for n, occ in where.items() if len(occ) > 1 and not all(occ))
        # Without a known page total the map may cover a slice of the source: check from its first page.
        lo = 1 if info["total"] else min(where)
        hi = info["total"] or max(where)
        step_ok = lambda n: n in where
        # bilingual documents mapped with "(odd)"/"(even)": ignore the other parity if every row uses one
        parities = {n % 2 for n in where}
        missing = [n for n in range(lo, hi + 1) if not step_ok(n) and (len(parities) == 2 or n % 2 in parities)]
        for label, pages in (("not mapped", missing), ("mapped twice", dup)):
            if pages:
                # legacy maps use many table layouts (bilingual odd/even pages, printed vs physical
                # numbering, side tables): report as a warning to review by hand, not as an error
                r.add("W112" if w.legacy else "E008", rp, f"{g}: pages {compress(pages)} {label}")
        if info["total"] and max(where) > info["total"]:
            r.add("E008", rp, f"{g}: maps page {max(where)} but source has {info['total']}")


def check_projects(w, r):
    prof_names = {prof.get("name", pp.stem) for pp, prof in w.profiles}
    decided = set()
    for jp, pj in w.projects:
        jr = w.rel(jp)
        if not pj.get("id"):
            r.add("E021", jr, "missing id")
        if pj.get("profile") not in prof_names:
            r.add("E021", jr, f"unknown profile '{pj.get('profile')}'")
        for d in pj.get("decisions") or []:
            if not isinstance(d, dict):
                r.add("E021", jr, repr(d)[:60]); continue
            did = d.get("id", "?")
            for k in ("id", "topic", "decision", "basis", "date"):
                if not d.get(k):
                    r.add("E021", jr, f"{did}: missing '{k}'")
            topic = str(d.get("topic", "")).replace("\\", "/")
            tp = (w.root / topic).resolve()
            if topic and tp not in w.pages:
                r.add("E021", jr, f"{did}: unknown topic '{topic}'"); continue
            if d.get("key") is not None:
                prof = next((pf for pp, pf in w.profiles if pf.get("name", pp.stem) == pj.get("profile")), None)
                vals = topic_values(w, w.pages[tp]["fm"] or {}).get(d["key"], [])
                if not vals:
                    r.add("E021", jr, f"{did}: no source value with key '{d['key']}' on {topic}")
                elif prof is not None and isinstance(d.get("value"), (int, float)) and d.get("unit"):
                    binding = sorted((applicability(prof, v["sid"])[1], v) for v in vals
                                     if applicability(prof, v["sid"])[0] == "binding" and v["dir"] != "info")
                    if binding:
                        gov = binding[0][1]
                        mine = base_value(d["value"], d["unit"])
                        if mine[1] != gov["base"][1]:
                            r.add("E021", jr, f"{did}: unit {d['unit']} cannot be compared with {gov['unit']}")
                        elif stricter(gov["base"][0], mine[0], gov["dir"]):
                            r.add("E024", jr, f"{did}: {d['key']} {d['value']:g} {d['unit']} is weaker than "
                                              f"{gov['sid']} {fmt_value(gov)} ({gov['dir']})")
            if d.get("conflict"):
                if (topic, d["conflict"]) not in w.topic_conflicts:
                    r.add("E021", jr, f"{did}: no conflict '{d['conflict']}' in {topic}")
                decided.add((topic, d["conflict"]))
    for (topic, cid), st in w.topic_conflicts.items():
        if st == "resolved-by-project" and (topic, cid) not in decided:
            r.add("E020", topic, cid)


def compress(nums):
    out, start = [], None
    for i, n in enumerate(nums):
        if start is None:
            start = n
        if i == len(nums) - 1 or nums[i + 1] != n + 1:
            out.append(f"{start}" if start == n else f"{start}-{n}"); start = None
    s = ", ".join(out)
    return s if len(s) < 80 else s[:77] + "..."


def check_links(w: Wiki, r: Report):
    inbound = collections.Counter()
    for p, pg in w.pages.items():
        if p.stem.lower() == "log":  # history: old links are expected to rot
            continue
        text = FENCE_RE.sub("", pg["body"])
        for l in WIKILINK_RE.findall(text):
            l = l.strip()
            if "..." in l or not l:
                continue
            stem = Path(l).stem.lower() if l.endswith(".md") else Path(l).name.lower()
            hits = w.by_stem.get(stem)
            if not hits and "/" in l:  # path-style wikilink: file, file.md or folder/index.md
                base = (p.parent / l).resolve()
                hits = [x for x in (base.with_suffix(".md"), base / "index.md") if x in w.pages]
            if hits:
                inbound.update(hits)
            else:
                r.add("E005", w.rel(p), f"[[{l.strip()}]]")
        for l in MDLINK_RE.findall(text):
            if re.match(r"^[a-z]+://", l):
                continue
            t = (p.parent / l).resolve()
            if t in w.pages:
                inbound[t] += 1
            elif not t.exists():
                r.add("E005", w.rel(p), l)
    for p in w.pages:
        stem = p.stem.lower()
        if inbound[p] == 0 and not any(k in stem for k in NO_ORPHAN) and not p.stem.isupper():
            r.add("W103", w.rel(p))


def validate(root: Path, legacy: bool, raw_root=None):
    w = Wiki(root, legacy, raw_root)
    r = Report()
    if w.has_registry:
        check_registry(w, r)
    stats = collections.Counter()
    for p, pg in w.pages.items():
        rp = w.rel(p)
        fm, ptype = pg["fm"], None
        ptype = w.page_type(p, fm or {})
        if ptype == "index" or p.name in ("README.md", "AGENTS.md", "LOG.md", "SPEC.md", "CLAUDE.md") \
                or p.stem.isupper() or ".bak" in p.name:  # docs / instruction files / backups
            continue
        if fm is None:
            if pg["err"] or ptype != "coverage":
                r.add("E001", rp, pg["err"] or "no frontmatter")
            if ptype == "coverage":
                check_coverage(w, p, {}, pg["body"], r)
            continue
        stats["type:" + ptype] += 1
        if ptype == "coverage":
            check_coverage(w, p, fm, pg["body"], r)
            continue
        st = check_verification(w, p, fm, ptype, r)
        stats["verification:" + str(st)] += 1
        if ptype == "source-page":
            check_source_page(w, p, fm, pg["body"], r)
        elif ptype == "topic":
            check_topic(w, p, fm, r, pg["body"])
            sil = fm.get("sources_silent") or []
            stats["topic:sources_silent_entries"] += len(sil)
    check_links(w, r)
    check_projects(w, r)
    for pp, prof in w.profiles:
        seen = collections.Counter()
        for key in PROFILE_LISTS:
            for sid in profile_ids(prof, key):
                seen[sid] += 1
                if key != "excluded" and w.has_registry and sid not in w.sources:
                    r.add("E019", w.rel(pp), f"{key}: unknown source '{sid}'")
        for sid, n in seen.items():
            if n > 1:
                r.add("E019", w.rel(pp), f"'{sid}' is listed {n} times")
    for e in dict.fromkeys(w.raw_errors):
        r.add("W117", "sources.yaml", e)
    stats["pages"] = len(w.pages)
    return w, r, stats


def print_report(w, r, stats, maxn):
    print(f"EDKA validate  root={w.root}  mode={'legacy' if w.legacy else 'strict'}  "
          f"registry={'yes (%d sources)' % len(w.sources) if w.has_registry else 'none'}  profiles={len(w.profiles)}")
    print("pages:", stats["pages"], " ", ", ".join(f"{k}={v}" for k, v in sorted(stats.items()) if k != "pages"))
    for code in sorted(r.items):
        items = r.items[code]
        print(f"\n{code} x{len(items)}  {CODES.get(code, '')}")
        for it in items[:maxn]:
            print(f"   {it['path']}  {it['msg']}")
        if len(items) > maxn:
            print(f"   ... {len(items) - maxn} more")
    print(f"\nRESULT: {r.errors()} error(s), {r.warnings()} warning(s)")


def sha256(p: Path):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def registry_path(root: Path):
    return root / (load_yaml(root / "edka.yaml", {}) or {}).get("registry", "sources.yaml")


def set_registry_field(text, sid, key, value):
    """Set `key: value` inside the registry entry `sid`, editing only that line.
    Comments, ordering and formatting of everything else are kept."""
    m = re.search(r"^-\s+id:\s*['\"]?" + re.escape(sid) + r"['\"]?\s*(#.*)?$", text, re.M)
    if not m:
        raise KeyError(sid)
    nxt = re.search(r"^-\s", text[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(text)
    block = text[m.start():end]
    ind = re.search(r"\n([ \t]+)\S", block)
    ind = ind.group(1) if ind else "  "
    line = f"{ind}{key}: {value}"
    fm = re.search(r"^" + re.escape(ind) + re.escape(key) + r":[^\n]*$", block, re.M)
    if fm:
        old = fm.group(0)
        comment = re.search(r"\s+#.*$", old)
        new_block = block[:fm.start()] + line + (comment.group(0) if comment else "") + block[fm.end():]
    else:
        anchor = re.search(r"^" + re.escape(ind) + r"raw:[^\n]*\n", block, re.M)
        pos = anchor.end() if anchor else block.index("\n") + 1 if "\n" in block else len(block)
        if pos == len(block) and not block.endswith("\n"):
            line = "\n" + line
        new_block = block[:pos] + line + "\n" + block[pos:]
    return text[:m.start()] + new_block + text[end:]


def cmd_hash(root: Path, raw_root=None):
    reg_path = registry_path(root)
    reg = load_yaml(reg_path, [])
    if not reg:
        sys.exit(f"edka: no registry at {reg_path}")
    base = Path(raw_root) if raw_root else root
    text = reg_path.read_text(encoding="utf-8")
    for s in reg:
        raw = base / str(s.get("raw", ""))
        if raw.is_file():
            new = sha256(raw)
            print(f"{s['id']}: {'unchanged' if s.get('sha256') == new else 'set'} {new[:12]}")
            if s.get("sha256") != new:
                text = set_registry_field(text, s["id"], "sha256", new)
        else:
            print(f"{s['id']}: raw missing ({s.get('raw')})")
    reg_path.write_text(text, encoding="utf-8", newline="\n")


def cmd_new_source(root: Path, a):
    reg_path = registry_path(root)
    reg = load_yaml(reg_path, []) or []
    if any(s.get("id") == a.id for s in reg):
        sys.exit(f"edka: source '{a.id}' already registered")
    folder = f"sources/{a.id}"
    entry = {"id": a.id, "title": a.title, "edition": str(a.edition), "kind": a.kind, "raw": a.raw,
             "pages": a.pages, "transcription": "paraphrase" if a.paraphrase else "verbatim",
             "folder": folder, "status": "active"}
    if a.not_redistributable:
        entry["redistributable"] = False
    raw = (Path(a.raw_root) if a.raw_root else root) / a.raw
    if raw.is_file():
        entry["sha256"] = sha256(raw)
    text = reg_path.read_text(encoding="utf-8") if reg_path.exists() else ""
    if text and not text.endswith("\n"):
        text += "\n"
    text += yaml.safe_dump([entry], sort_keys=False, allow_unicode=True)   # appended: existing text untouched
    reg_path.write_text(text, encoding="utf-8", newline="\n")
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    cov = d / "coverage.md"
    if not cov.exists():
        rows = "\n".join(f"| {n} | — | pending |" for n in range(1, a.pages + 1)) if a.pages <= 60 \
            else f"| 1-{a.pages} | — | pending |"
        cov.write_text(f"---\ntype: coverage\nsource: {a.id}\nupdated: {dt.date.today()}\n---\n"
                       f"# Coverage — {a.title} {a.edition}\n\n| Pages | Wiki page | Treatment |\n|---|---|---|\n{rows}\n",
                       encoding="utf-8", newline="\n")
    print(f"registered {a.id}; created {folder}/coverage.md ({a.pages} pages pending)")


def cmd_new_topic(root: Path, a):
    path = root / a.path
    if path.exists():
        sys.exit(f"edka: {a.path} exists")
    w = Wiki(root, False)
    ids = [x.strip() for x in a.sources.split(",") if x.strip()]
    unknown = [i for i in ids if i not in w.sources]
    if unknown:
        sys.exit(f"edka: unknown source id(s): {', '.join(unknown)}")
    cov = "\n".join(f"  - {{source: {i}, locators: [], depth: raw}}" for i in ids)
    others = [i for i, s in w.sources.items() if i not in ids and s.get("status") == "active"]
    sil = "\n".join(f"  - {{source: {i}, reason: \"TODO: checked? what was read?\", depth: not-opened}}" for i in others)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""---
type: topic
title: "{a.title}"
sources_covered:
{cov}
sources_silent:{chr(10) + sil if sil else " []"}
conflicts: []
derived_from: []
verification: {{status: derived}}
updated: {dt.date.today()}
---
What each source says. Keep this page neutral: no "binding" column and no answer for one project.
Link every row to its source page; `edka.py view <topic> --profile <name>` adds applicability.

| Source | What it says | Value | Page |
|---|---|---|---|
""", encoding="utf-8", newline="\n")
    print(f"created {a.path}: {len(ids)} covered, {len(others)} other active sources listed as silent (depth not-opened, to confirm)")


def cmd_answer_check(root: Path, answer: Path, profile=None, project_id=None):
    """Print, for every wiki page an answer links to, its source, pages, transcription and verification,
    then list numbers in the answer that none of the linked pages (or the project's decisions) contain."""
    w = Wiki(root, False)
    project = None
    if project_id:
        project = next((pj for _, pj in w.projects if pj.get("id") == project_id), None)
        if not project:
            sys.exit(f"edka: no project '{project_id}' in projects/")
        profile = profile or project.get("profile")
    text = answer.read_text(encoding="utf-8")
    linked = []
    for l in MDLINK_RE.findall(text):
        for base in (answer.parent, w.root):
            t = (base / l).resolve()
            if t in w.pages:
                linked.append(t); break
    for l in WIKILINK_RE.findall(text):
        linked += w.by_stem.get(Path(l.strip()).stem.lower(), [])
    linked = list(dict.fromkeys(linked))
    print(f"answer: {answer}  linked wiki pages: {len(linked)}")
    prof = find_profile(w, profile) if profile else None
    print(f"{'page':58} {'source':16} {'pages':8} {'mode':10} {'applies':11} verification")
    bad = []
    known = set()
    for p in linked:
        fm = w.pages[p]["fm"] or {}
        v = fm.get("verification")
        st = v.get("status") if isinstance(v, dict) else (legacy_status(v) if isinstance(v, str) else None)
        sid = fm.get("source", "")
        mode = fm.get("transcription") or (w.sources.get(sid) or {}).get("transcription", "")
        if fm.get("type") == "topic":
            st = f"{st} (topic: cite the source pages instead)"
        app = applicability(prof, sid)[0] if (prof and sid) else "-"
        if app == "excluded":
            bad.append(sid)
        print(f"{w.rel(p)[:58]:58} {str(sid)[:16]:16} {str(fm.get('source_pages', ''))[:8]:8} {str(mode)[:10]:10} {app:11} {st}")
        known |= numbers_in(w.pages[p]["body"])
    if project:
        used = []
        for d in project.get("decisions") or []:
            if not isinstance(d, dict):
                continue
            dn = numbers_in(f"{d.get('value', '')} {d.get('unit', '')}\n{d.get('decision', '')}")
            if dn & numbers_in(text):
                used.append(d.get("id"))
            known |= dn
        print(f"\nproject {project.get('id')} (profile {profile}): decisions supporting numbers in the answer:",
              ", ".join(used) if used else "none")
    missing = sorted(numbers_in(text) - known)
    print("\nnumbers with no support on a linked page:", ", ".join(missing) if missing else "none")
    weak = [w.rel(p) for p in linked if not isinstance((w.pages[p]["fm"] or {}).get("verification"), (dict, str))
            or "unverified" in str((w.pages[p]["fm"] or {}).get("verification"))]
    if weak:
        print("unverified pages cited:", ", ".join(weak))
    if bad:
        print("cites sources this profile EXCLUDES:", ", ".join(sorted(set(bad))))
    return 1 if (missing or bad) else 0


def find_profile(w, name):
    for pp, prof in w.profiles:
        if name in (prof.get("name"), pp.stem):
            return prof
    sys.exit(f"edka: no profile '{name}' (have: {', '.join(prof.get('name', pp.stem) for pp, prof in w.profiles)})")


def row_sources(w, topic_path, row):
    out = []
    for l in MDLINK_RE.findall(row):
        t = (topic_path.parent / l).resolve()
        if t in w.pages:
            sid = (w.pages[t]["fm"] or {}).get("source")
            if sid:
                out.append(sid)
    for l in WIKILINK_RE.findall(row):
        for t in w.by_stem.get(Path(l.strip()).stem.lower(), []):
            sid = (w.pages[t]["fm"] or {}).get("source")
            if sid:
                out.append(sid)
    return list(dict.fromkeys(out))


ORDER = {"binding": 0, "client": 1, "reference": 2, "not-listed": 3, "excluded": 4}
LABEL = {"binding": "**Binding**", "client": "Client", "reference": "Reference", "not-listed": "Not in profile"}
SRC_TAG_RE = re.compile(r"⟦src:([^⟧]+)⟧")
LINK_TARGET_RE = re.compile(r"\]\(([^)\s#]+)(#[^)]*)?\)")


def relink(line, from_dir, to_dir):
    """Rewrite relative Markdown links in `line` written for `from_dir` so they work from `to_dir`."""
    if from_dir == to_dir:
        return line
    def fix(m):
        target = m.group(1)
        if re.match(r"^[a-z]+:", target) or target.startswith("/"):
            return m.group(0)
        abs_target = (from_dir / target).resolve()
        try:
            new = os.path.relpath(abs_target, to_dir).replace("\\", "/")
        except ValueError:  # different drive on Windows: no relative path exists
            new = abs_target.as_posix()
        return f"]({new}{m.group(2) or ''})"
    return LINK_TARGET_RE.sub(fix, line)


def project_decisions(project, topic_rel):
    return [d for d in (project or {}).get("decisions") or []
            if isinstance(d, dict) and str(d.get("topic", "")).replace("\\", "/") == topic_rel]


def body_blocks(lines):
    """Split a page body into blocks: ('table', [lines]) | ('fence', [lines]) | ('para', [lines]) | ('blank', [line])."""
    i, out = 0, []
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            out.append(("fence", lines[i:j + 1])); i = j + 1
        elif s.startswith("|"):
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            out.append(("table", lines[i:j])); i = j
        elif not s:
            out.append(("blank", [lines[i]])); i += 1
        else:
            j = i
            while j < len(lines) and lines[j].strip() and not lines[j].strip().startswith(("|", "```")):
                j += 1
            out.append(("para", lines[i:j])); i = j
    return out


def render_view(w, topic_path, prof, project=None, out_dir=None):
    topic_path = topic_path.resolve()
    pg = w.pages[topic_path]
    fm, body = pg["fm"] or {}, pg["body"]
    name = prof.get("name", "?")
    out_dir = Path(out_dir).resolve() if out_dir else topic_path.parent
    rl = lambda line: relink(line, topic_path.parent, out_dir)
    trel = w.rel(topic_path)
    decisions = project_decisions(project, trel)
    head = f"# {fm.get('title', topic_path.stem)} — profile `{name}`"
    if project:
        head += f", project `{project.get('id')}`"
    out = [head, ""]
    if prof.get("applies_to"):
        out += [f"_Applies to: {prof['applies_to']}._", ""]
    hidden_rows, hidden_paras = set(), 0

    covered = source_ids(fm.get("sources_covered"))
    gov = [(applicability(prof, s)[1], s) for s in covered if applicability(prof, s)[0] == "binding"]
    out.append("## What governs")
    if gov:
        for rank, s in sorted(gov):
            sc = scope_of(prof, s)
            out.append(f"- **{s}** (binding #{rank + 1}{': ' + sc if sc else ''})")
    else:
        out.append("- No binding source in this profile covers this topic. A project decision is needed.")
    for s in [s for s in covered if applicability(prof, s)[0] == "client"]:
        out.append(f"- {s} (client requirement: applies where stricter)")
    for e in fm.get("sources_silent") or []:
        if isinstance(e, dict) and applicability(prof, e.get("source"))[0] in ("binding", "client"):
            out.append(f"- {e['source']} is {applicability(prof, e['source'])[0]} here but **silent**: "
                       f"{e.get('reason', '')} (read depth: {e.get('depth')})")
    out.append("")

    by_conflict = {d.get("conflict"): d for d in decisions if d.get("conflict")}
    if fm.get("conflicts"):
        out.append("## Conflicts")
        for c in fm["conflicts"]:
            if not isinstance(c, dict):
                continue
            st, d = c.get("status"), by_conflict.get(c.get("id"))
            if d:
                note = (f"**project decision {d.get('id')}**: {d.get('decision')} "
                        f"(basis: {d.get('basis')}; {d.get('by', '?')}, {d.get('date', '?')})")
                if st == "resolved-by-profile":
                    note += f". Without it: {governing(prof, c.get('between') or [])[1]}"
            elif st == "resolved-by-profile":
                note = governing(prof, c.get("between") or [])[1]
            elif st == "accepted-difference":
                note = "accepted difference: both statements stand, each in its own scope"
            elif st == "resolved-by-project":
                note = ("**needs a project decision**: none recorded for this project" if project
                        else "resolved per project: run with --project to see the decision")
            else:
                note = "**OPEN**: not resolved"
            out.append(f"- **{c.get('id')}** ({' vs '.join(c.get('between') or [])}): {note}. {c.get('summary', '')}")
        out.append("")
    tv = topic_values(w, fm)
    if any(len(v) > 1 for v in tv.values()) or any(d.get("key") for d in decisions):
        out.append("## Values compared")
        out.append("Only values with the same key (the same quantity, measured the same way) are compared.")
        out.append("")
        for key, vals in tv.items():
            shown = [v for v in vals if applicability(prof, v["sid"])[0] != "excluded"]
            dec = [d for d in decisions if d.get("key") == key]
            if len(shown) < 2 and not dec:
                continue
            out.append(f"**{key}**")
            out.append("")
            out.append("| Source | Applies here | Value | Page | |")
            out.append("|---|---|---|---|---|")
            comp = comparable(shown) if shown else False
            gov = None
            best = strictest(shown) if comp else None
            ranked = sorted(shown, key=lambda v: (ORDER[applicability(prof, v["sid"])[0]], applicability(prof, v["sid"])[1] or 0))
            for v in ranked:
                k, rank = applicability(prof, v["sid"])
                label = LABEL[k] + (f" #{rank + 1}" if k == "binding" else "")
                link = rl(f"[{v['sid']}]({os.path.relpath(v['page_path'], topic_path.parent).replace(chr(92), '/')})")
                mark = "strictest" if v is best else ""
                pg = f"⟦p.{v['page']}⟧" if v.get("page") else ""
                out.append(f"| {link} | {label} | {fmt_value(v)} ({v['dir']}) | {pg} | {mark} |")
            out.append("")
            if comp:
                binding = sorted((applicability(prof, v["sid"])[1], v) for v in shown if applicability(prof, v["sid"])[0] == "binding")
                client = [v for v in shown if applicability(prof, v["sid"])[0] == "client"]
                if binding:
                    gov = binding[0][1]
                    line = f"→ Governs here: **{fmt_value(gov)}** ({gov['sid']}, binding #{binding[0][0] + 1})"
                    stricter_client = [c for c in client if stricter(c["base"][0], gov["base"][0], gov["dir"])]
                    if stricter_client:
                        c = strictest(stricter_client)
                        line += f"; client {c['sid']} is stricter: **{fmt_value(c)}** applies"
                    if best is not gov and best not in client and applicability(prof, best["sid"])[0] != "binding":
                        line += f". {best['sid']} ({applicability(prof, best['sid'])[0]}) is stricter at {fmt_value(best)}, not required here"
                    out.append(line + ".")
                else:
                    out.append(f"→ No binding value under this profile. Strictest available: {fmt_value(best)} ({best['sid']}).")
            elif len(shown) > 1:
                out.append("→ Not comparable automatically (different units or directions): judge by hand.")
            for d in dec:
                cmp = ""
                if gov is not None and isinstance(d.get("value"), (int, float)) and d.get("unit"):
                    mine = base_value(d["value"], d["unit"])
                    if mine[1] == gov["base"][1]:
                        cmp = (" — **weaker than the binding requirement**" if stricter(gov["base"][0], mine[0], gov["dir"])
                               else " — equal to the binding requirement" if mine[0] == gov["base"][0]
                               else f" — stricter than the binding {fmt_value(gov)}")
                out.append(f"→ Project decision **{d.get('id')}**: {d.get('value')} {d.get('unit')}{cmp} ({d.get('decision')})")
            out.append("")
    other = [d for d in decisions if not d.get("conflict")]
    if other:
        out.append("## Project decisions on this topic")
        for d in other:
            out.append(f"- **{d.get('id')}** {d.get('question', '')}: {d.get('decision')} "
                       f"(basis: {d.get('basis')}; {d.get('by', '?')}, {d.get('date', '?')})")
        out.append("")

    out.append("## Source values (from the neutral topic page)")
    for kind, blk in body_blocks(body.splitlines()):
        if kind == "para":
            text = "\n".join(blk)
            tags = [t.strip() for m in SRC_TAG_RE.findall(text) for t in m.split(",")]
            if any(applicability(prof, t)[0] == "excluded" for t in tags):
                hidden_paras += 1
                continue
            out += [rl(SRC_TAG_RE.sub("", l).rstrip()) for l in blk]
        elif kind == "table" and len(blk) >= 2 and set(blk[1].strip()) <= set("|-: "):
            cells = blk[0].strip().strip("|").split("|")
            out.append("| " + cells[0].strip() + " | Applies here | " + " | ".join(c.strip() for c in cells[1:]) + " |")
            out.append("|---" * (len(cells) + 1) + "|")
            rows = []
            for row in blk[2:]:
                row = row.strip()
                sids = row_sources(w, topic_path, row)
                kinds = [applicability(prof, sid) for sid in sids] or [("not-listed", None)]
                k, rank = min(kinds, key=lambda x: (ORDER[x[0]], x[1] or 0))
                if k == "excluded":
                    hidden_rows.update(sids); continue
                c = row.strip("|").split("|")
                label = LABEL[k] + (f" #{rank + 1}" if k == "binding" else "")
                rows.append(((ORDER[k], rank or 0), rl("| " + c[0].strip() + f" | {label} | " + " | ".join(x.strip() for x in c[1:]) + " |")))
            out += [r for _, r in sorted(rows, key=lambda x: x[0])]
        else:
            out += [rl(l) for l in blk]
    notes = []
    if hidden_rows:
        notes.append(f"rows from {', '.join(sorted(hidden_rows))}")
    if hidden_paras:
        notes.append(f"{hidden_paras} paragraph(s) about excluded sources")
    if notes:
        out += ["", f"_Hidden because this profile excludes them: {'; '.join(notes)}._"]
    out += ["", f"_Generated by `edka.py view` from `{trel}` on {dt.date.today()}. Cite the source pages, not this view._"]
    return "\n".join(out) + "\n"


def cmd_view(root: Path, a):
    w = Wiki(root, False)
    tp = (root / a.topic).resolve()
    if tp not in w.pages:
        sys.exit(f"edka: no page {a.topic}")
    project = None
    if a.project:
        project = next((pj for _, pj in w.projects if pj.get("id") == a.project), None)
        if not project:
            sys.exit(f"edka: no project '{a.project}' in projects/")
    pname = a.profile or (project or {}).get("profile")
    if not pname:
        sys.exit("edka: give --profile or --project")
    out_dir = Path(a.out).resolve().parent if a.out else None
    text = render_view(w, tp, find_profile(w, pname), project, out_dir)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8")
        print(f"wrote {a.out}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)


def main(argv=None):
    # Windows consoles default to a legacy code page; page names, ⟦p.N⟧ markers and paths may not fit it.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="edka", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate"); v.add_argument("root"); v.add_argument("--json"); v.add_argument("--legacy", action="store_true")
    v.add_argument("--max", type=int, default=8); v.add_argument("--raw-root", help="folder holding raw files kept outside the repo")
    s = sub.add_parser("stats"); s.add_argument("root"); s.add_argument("--legacy", action="store_true")
    h = sub.add_parser("hash"); h.add_argument("root"); h.add_argument("--raw-root")
    ns = sub.add_parser("new-source"); ns.add_argument("root")
    for k in ("--id", "--title", "--edition", "--raw"):
        ns.add_argument(k, required=True)
    ns.add_argument("--kind", default="normative", choices=KINDS); ns.add_argument("--pages", type=int, required=True)
    ns.add_argument("--paraphrase", action="store_true"); ns.add_argument("--not-redistributable", action="store_true")
    ns.add_argument("--raw-root")
    nt = sub.add_parser("new-topic"); nt.add_argument("root"); nt.add_argument("path")
    nt.add_argument("--title", required=True); nt.add_argument("--sources", required=True)
    ac = sub.add_parser("answer-check"); ac.add_argument("root"); ac.add_argument("answer"); ac.add_argument("--profile")
    ac.add_argument("--project", help="project id: uses its profile and accepts numbers set by its decisions")
    vw = sub.add_parser("view"); vw.add_argument("root"); vw.add_argument("topic"); vw.add_argument("--profile")
    vw.add_argument("--project", help="project id from projects/*.yaml (its profile is used unless --profile is given)"); vw.add_argument("--out")
    a = ap.parse_args(argv)
    root = Path(a.root)
    if a.cmd == "hash":
        return cmd_hash(root, a.raw_root)
    if a.cmd == "new-source":
        return cmd_new_source(root, a)
    if a.cmd == "new-topic":
        return cmd_new_topic(root, a)
    if a.cmd == "answer-check":
        return cmd_answer_check(root, Path(a.answer), a.profile, a.project)
    if a.cmd == "view":
        return cmd_view(root, a)
    w, r, stats = validate(root, a.legacy, getattr(a, "raw_root", None))
    if a.cmd == "stats":
        print(json.dumps(stats, indent=1, sort_keys=True)); return 0
    print_report(w, r, stats, a.max)
    if a.json:
        Path(a.json).write_text(json.dumps({"root": str(w.root), "legacy": w.legacy, "stats": stats,
                                            "errors": r.errors(), "warnings": r.warnings(),
                                            "findings": r.items, "codes": CODES}, indent=1, ensure_ascii=False,
                                           default=str), encoding="utf-8")
    return 1 if r.errors() else 0


if __name__ == "__main__":
    sys.exit(main())
