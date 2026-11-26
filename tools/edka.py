#!/usr/bin/env python3
"""EDKA validator and helper CLI. Works with any agent or person: plain files in, plain text or JSON out.

Read-only (safe to run at any time; they never change a file):
    edka validate <wiki-root> [--strict] [--json report.json] [--legacy] [--raw-root DIR] [--max N]
    edka stats    <wiki-root> [--legacy]
    edka view     <wiki-root> <topic.md> (--profile NAME | --project ID)        # prints to the screen
    edka answer-check <wiki-root> <answer.md> [--profile NAME | --project ID]
    edka explain  <CODE>                                                        # what a finding means, how to fix it

Write files (run them on purpose):
    edka hash       <wiki-root> [--raw-root DIR] [--force ID ...]   # sets missing sha256 lines; a changed raw
                                                                    # file is only re-hashed with --force ID
    edka new-source <wiki-root> --id ID --title T --edition E --raw PATH --pages N [--kind K] [--paraphrase]
                                # appends one entry to sources.yaml; creates sources/<id>/coverage.md
    edka new-topic  <wiki-root> <topics/branch/name.md> --title T --sources id1,id2   # creates one new page
    edka view ... --out FILE                                        # writes the view to FILE

Existing text in sources.yaml (comments included) is never rewritten. No command calls a model or the network.
Needs Python 3.9+ and PyYAML; pdftotext is optional (raw-text checks on PDFs).

The code follows the layers of SPEC.md:
  1 Vocabulary and findings   2 Text and numbers      3 Loading a wiki (fails closed)
  4 Sources layer             5 Topics layer          6 Profiles layer       7 Projects layer
  8 Evidence and verification 9 Links                 10 Conformance levels and the validate run
  11 Views and answers        12 Writers              13 Command line
"""
from __future__ import annotations

import argparse, collections, datetime as dt, hashlib, json, os, re, shutil, subprocess, sys, tempfile, unicodedata
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("edka: PyYAML is required (pip install pyyaml)")

__version__ = "0.2.2"

# =====================================================================================================
# 1. Vocabulary and findings
# =====================================================================================================
VER_STATUS = ["unverified", "author-checked", "sample-audit", "independent-partial", "independent", "derived"]
DEPTHS = ["raw", "wiki", "index", "not-opened"]
CONFLICT_STATUS = ["open", "resolved-by-profile", "resolved-by-project", "accepted-difference"]
TREATMENTS = ["transcribed", "summarised", "not-ingested", "no-relevant-content", "pending"]
CARRIED = ("transcribed", "summarised")
KINDS = ["normative", "guidance", "client-requirement", "catalogue", "other"]
PAGE_TYPES = ["source-page", "topic", "coverage", "note", "index"]
TRANSCRIPTION = ["verbatim", "paraphrase"]
LEVELS = ["core", "coverage", "synthesis", "governed"]
PROFILE_LISTS = ("binding", "client", "reference", "excluded")
NEGATION_RE = re.compile(r"\b(not|no|never|nor|neither|without|except|unless|cannot|can't|shan't|won't)\b")

# code: (message, how to fix). E = error, W = warning, I = information (never fails a run).
CODES = {
    "E000": ("wiki cannot be checked: root, edka.yaml or registry missing or unreadable",
             "Point the command at the wiki root (the folder holding edka.yaml and sources.yaml). Use --legacy only for pre-EDKA wikis."),
    "E001": ("frontmatter or YAML file missing, invalid or with an invalid date",
             "Fix the YAML between the --- lines (quote text containing ':' or '#'); dates are YYYY-MM-DD and must exist."),
    "E002": ("required field missing", "Add the field named in the finding (see SPEC.md section 4)."),
    "E003": ("unknown source id", "Register the source in sources.yaml, or correct the id."),
    "E004": ("invalid verification status", f"Use one of: {', '.join(VER_STATUS)}."),
    "E005": ("broken internal link", "Correct the link target, or create the page."),
    "E006": ("raw file missing", "Put the original file at the registered path, or pass --raw-root for files kept outside the repo."),
    "E007": ("raw file changed since it was hashed",
             "Do NOT just re-hash. Re-verify every page of this source against the new file, then run `edka hash <root> --force <id>`."),
    "E008": ("coverage map gap, overlap, or carried page without a wiki page",
             "Every physical page must appear once with a treatment; transcribed/summarised rows must link their wiki page."),
    "E009": ("sources_silent / sources_covered entry invalid", "Each entry needs source, reason (silent only) and depth: raw|wiki|index|not-opened."),
    "E010": ("invalid conflict entry", "A conflict needs id, between: [two or more registered ids] and a valid status."),
    "E011": ("conflict marked resolved-by-profile but no profile resolves it",
             "Add a profile that makes one side binding, or change the status to resolved-by-project / accepted-difference / open."),
    "E012": ("topic uses a source that edka.yaml excludes from all topics", "Remove the source from the topic (rows, derived_from, sources_covered)."),
    "E013": ("independent verification without date, by and ref", "Record who verified (by), when (date) and the report (ref)."),
    "E014": ("invalid registry entry", "See SPEC.md section 3: id, title, edition, kind, raw, pages, transcription, folder, status; ids unique."),
    "E015": ("number not found on the source page it is attributed to",
             "Copy the value exactly from the linked source page, link the right page, or mark a computed line with ⟦calc⟧."),
    "E016": ("verbatim quote does not match the raw text (missing, out of order, or an ellipsis drops a negation)",
             "Quote the source exactly; use … only where nothing that changes the meaning is cut. Paraphrase without '>'."),
    "E017": ("independence not shown: author missing or the same as the verifier",
             "Record author and by; the verifier must be a different agent or person."),
    "E018": ("topic states applicability (a binding/applies column or a per-jurisdiction answer)",
             "Keep topics neutral; precedence belongs in profiles and is shown by `edka view --profile`."),
    "E019": ("invalid profile", "Profiles list registered sources once each, in binding / client / reference / excluded."),
    "E020": ("conflict is resolved-by-project but no project records a decision for it",
             "Add a decision with this topic and conflict id to projects/<id>.yaml."),
    "E021": ("invalid project file", "Each decision needs id, topic, decision, basis, date; its topic, conflict and key must exist."),
    "E022": ("invalid structured value", "Each value needs key, numeric value, unit and dir: min|max|info."),
    "E023": ("structured value not stated in the page body", "Write the value in the page text too; the values: list repeats the text."),
    "E024": ("project decision is less strict than the requirement that applies (binding, or a stricter client value)",
             "A project may go above the code, never below it. Raise the value or change the profile."),
    "E025": ("unknown page type", f"Use type: {' | '.join(PAGE_TYPES)}."),
    "E026": ("invalid source_pages", "Use physical PDF pages like \"12\", \"12-15\" or \"12, 14\", within the registered page count."),
    "E027": ("verification evidence missing or does not support the claim",
             "The ref must exist and name this source, its pages and the verifier (`by`); list what was not checked."),
    "E028": ("wiki does not meet its declared conformance level", "Add what the level requires (SPEC.md section 1) or lower `level:`."),
    "E029": ("invalid field value", "See the finding; allowed values are in SPEC.md."),
    "E030": ("source listed both as covered and as silent on one topic", "A source either says something on the topic or is silent; pick one."),
    "E031": ("number on a source page not found in the raw text of its pages (text source, so not an OCR difference)",
             "Copy the value exactly from the source, or mark a computed line with ⟦calc⟧."),
    "W101": ("topic older than a page it is derived from (stale synthesis)", "Re-read the changed source page and update the topic."),
    "W102": ("page marker or value page outside the page's source_pages", "Correct the marker or source_pages."),
    "W103": ("orphan page (no inbound links)", "Link the page from an index or topic."),
    "W104": ("source has no coverage map", "Create <folder>/coverage.md (edka new-source does this)."),
    "W105": ("weak read depth (index/not-opened)", "Open the raw file and update depth, or treat the claim as unconfirmed."),
    "W106": ("registry entry has no sha256", "Run `edka hash <root>`."),
    "W107": ("topic relies on a withdrawn source", "Remove or replace the withdrawn source's content."),
    "W108": ("topic relies on a superseded source", "Use the newer edition; to keep the old one for history, list it under `history:` in the topic."),
    "W109": ("verification ref path not found", "Correct the ref or add the report."),
    "W110": ("derived page without derived_from", "List the pages the synthesis was derived from."),
    "W111": ("coverage treatment not in the EDKA vocabulary", f"Start the treatment with one of: {', '.join(TREATMENTS)}."),
    "W112": ("legacy coverage map: possible gap/overlap (check by hand)", "Review the map against the PDF."),
    "W114": ("independent verification without an author", "Record the author so independence can be checked."),
    "W115": ("verbatim page could not be checked (raw text not available)", "Provide the raw file (or --raw-root) or pdftotext."),
    "W116": ("number on a source page not found in the raw text of its pages", "Check the page image; OCR text may differ from the scan."),
    "W117": ("raw text could not be extracted", "Install pdftotext or check the file."),
    "W118": ("under this profile no side of a resolved-by-profile conflict is binding", "That profile needs a project decision."),
    "W119": ("topic table row with no link to a source page", "Link the row to the source page it reports."),
    "W120": ("topic paragraph names a source without a ⟦src:id⟧ tag", "Start the paragraph with ⟦src:id,…⟧."),
    "W121": ("one value key used with different units or directions", "Use one unit and direction per key, or separate keys."),
    "W122": ("ambiguous wikilink (several pages share the name)", "Use a relative Markdown link instead."),
    "W123": ("link differs in letter case from the file name (fails on Linux)", "Match the file name exactly."),
    "W124": ("same value key listed twice on one page", "Use one entry per key per page, or separate keys."),
    "W125": ("source page's pages not mapped to it in the coverage map", "Update the coverage map or source_pages."),
    "W126": ("verifier name looks like a variant of the author's", "Make sure a different agent or person verified the page."),
    "E032": ("⟦calc⟧ on a line with no calculation", "Use ⟦calc⟧ only on lines that show the arithmetic (=, +, −, ×, ÷)."),
    "E033": ("topic uses a source it does not list in sources_covered", "Add the source to sources_covered with locators and depth."),
    "W127": ("topic prose may state applicability", "Keep topics neutral; say what each source says, not which one to use."),
    "W129": ("sources give different values for the same key but no conflict lists them",
             "Add a conflict entry naming both sources (or mark the old one under history:)."),
    "W130": ("active source neither covered nor silent on this topic", "Assess it: add it to sources_covered or sources_silent."),
    "W131": ("profile makes a superseded source binding", "Bind the current edition, or say why the old one still applies."),
    "W132": ("project decision states a number but no key/value, so it cannot be compared with the code",
             "Add key, value and unit to the decision."),
    "I002": ("computed line (⟦calc⟧): not checked against sources", "Check the arithmetic by hand."),
    "I003": ("files ignored by edka.yaml ignore:", "Make sure no EDKA page is hidden."),
    "W200": ("legacy unstructured field (string instead of mapping)", "Convert to the structured form in SPEC.md."),
    "I001": ("raw file not present (source marked not redistributable); integrity not checked",
             "Pass --raw-root with your licensed copies to check hashes and numbers."),
}

# Warnings that become errors at a conformance level (on top of the explicit level checks).
LEVEL_PROMOTE = {
    "core": {"W106"},
    "coverage": {"W106", "W104"},
    "synthesis": {"W106", "W104"},
    "governed": {"W106", "W104", "W109", "W114", "W119", "W126", "W129"},
}


# Heuristic warnings: useful hints, but honest wikis can trigger them, so --strict never turns them into errors.
HEURISTIC = {"W103", "W105", "W116", "W127", "W130"}


class Report:
    def __init__(self):
        self.items = collections.defaultdict(list)
        self.promoted = set()

    def add(self, code, path, msg=""):
        self.items[code].append({"path": str(path), "msg": msg})

    def is_error(self, code):
        return code.startswith("E") or code in self.promoted

    def errors(self):
        return sum(len(v) for k, v in self.items.items() if self.is_error(k))

    def warnings(self):
        return sum(len(v) for k, v in self.items.items() if k.startswith("W") and not self.is_error(k))


# =====================================================================================================
# 2. Text and numbers
# =====================================================================================================
FM_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
MDLINK_RE = re.compile(r"\]\(([^)#\s]+\.md)(?:#[^)]*)?\)")
FENCE_RE = re.compile(r"```.*?```", re.S)
PMARK_RE = re.compile(r"⟦p\.(\d+)⟧")
SRC_TAG_RE = re.compile(r"⟦src:([^⟧]+)⟧")
CALC_MARK = "⟦calc⟧"
# a ⟦calc⟧ line must show its arithmetic: 'a = b', or an operator between two quantities with spaces around it
CALC_OK_RE = re.compile(r"\d[\w%½²°. ]*\s=\s*\d|\d[\w%½²°. ]*\s[+×÷*/−x-]\s+\d|\d\s*[+×÷]\s*\d")
PAGE_SPLIT_RE = re.compile(r"^=== page (\d+) ===$", re.M)

UNIT_ALIASES = {"per cent": "%", "lux": "lx", "minutes": "min", "minute": "min", "mins": "min", "hours": "h", "hour": "h", "hrs": "h",
                "seconds": "s", "second": "s", "sec": "s", "ohm": "Ω", "ohms": "Ω", "mm2": "mm²", "m2": "m²",
                "m3": "m³", "percent": "%", "metres": "m", "meters": "m", "metre": "m", "meter": "m",
                "ft-candles": "ft-candle", "kilograms": "kg"}
BASE_UNITS = ["%", "percent", "per cent", "lx", "lux", "cd", "lm", "ft-candles", "ft-candle",
              "MVA", "kVA", "VA", "kvar", "var", "MWh", "kWh", "MW", "kW", "W", "kV", "mV", "V", "kA", "mA", "A",
              "Ω", "ohms", "ohm", "kHz", "Hz", "°C", "°F", "dB(A)", "dB",
              "km", "mm²", "mm2", "mm", "cm", "m²", "m2", "m³", "m3", "metres", "meters", "metre", "meter", "m",
              "ms", "seconds", "second", "sec", "s", "minutes", "minute", "mins", "min", "hours", "hour", "hrs", "h",
              "kg", "kN", "N", "MPa", "kPa", "Pa", "bar"]
NUM_PART = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?"


HYPHEN_UNITS = ["minutes", "minute", "mins", "hours", "hour", "hrs", "seconds", "second", "metres", "meters",
                 "metre", "meter", "percent", "per cent"]


def build_num_re(extra_units=()):
    units = sorted(set(BASE_UNITS) | set(str(u) for u in (extra_units or ())), key=len, reverse=True)
    alt = "|".join(re.escape(u) for u in units)
    unit = r"(?:" + alt + r")(?:/(?:" + alt + r"))?"          # compound units such as W/m², m/s, %/m
    hyph = "|".join(re.escape(u) for u in sorted(HYPHEN_UNITS, key=len, reverse=True))
    # '90-minute' is a number; '4-A' (Table 4-A) and '2-N' (Annex 2-N) are not, so a hyphen is allowed only
    # before word units.
    return re.compile(r"(?<![\w.,/])(" + NUM_PART + r")(\s*½)?(?:\s*|-)(" + hyph + r"|" + unit + r")(?![A-Za-z0-9²³/])"
                      r"|(?<![\w.])(½)\s*(" + unit + r")(?![A-Za-z0-9²³/])")


NUM_RE = build_num_re()


def norm_unit(u):
    u = re.sub(r"\s+", " ", str(u).strip())
    if "/" in u:
        return "/".join(norm_unit(x) for x in u.split("/", 1))
    if u.lower().startswith("ft-candle"):
        return "ft-candle"
    if u == "Ω":
        return u
    return UNIT_ALIASES.get(u, UNIT_ALIASES.get(u.lower(), u))


def parse_number(v):
    v = v.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", v):     # 1,000 or 12,500.5: thousands separators
        return float(v.replace(",", ""))
    return float(v.replace(",", "."))                          # 0,5 or 1.5: decimal


def numbers_in(text, num_re=None):
    """Set of normalised 'value unit' strings, e.g. {'4 %', '1.5 h', '1000 V'}. Lines marked ⟦calc⟧ are skipped."""
    num_re = num_re or NUM_RE
    out = set()
    for line in text.splitlines():
        if CALC_MARK in line:
            continue
        line = re.sub(r"(\d*)\s?1⁄2", lambda m: (m.group(1) or "") + "½", line)  # 1 1/2 written with U+2044
        # '230/400 V' states 230 V and 400 V
        line = re.sub(r"(?<![\w.,/])(" + NUM_PART + r")/(" + NUM_PART + r")\s*([A-Za-z%°Ω][\w²³()°/%]*)",
                      lambda m: f"{m.group(1)} {m.group(3)} {m.group(2)} {m.group(3)}", line)
        for m in num_re.finditer(line):
            if m.group(4):
                val, unit = 0.5, m.group(5)
            else:
                val = parse_number(m.group(1)) + (0.5 if m.group(2) else 0)
                unit = m.group(3)
            if m.group(2) is None and "-" in m.group(0) and unit.lower() not in HYPHEN_UNITS:
                continue
            out.add(f"{val:g} {norm_unit(unit)}")
    return out


TIME_TO_MIN = {"s": 1 / 60, "ms": 1 / 60000, "min": 1.0, "h": 60.0}
LENGTH_TO_M = {"mm": 0.001, "cm": 0.01, "m": 1.0, "km": 1000.0}
VALUE_DIRS = ("min", "max", "info")   # min: a minimum requirement (higher is stricter); max: a maximum (lower is stricter)


def base_value(value, unit):
    """Value in a comparable base unit (time in minutes, length in metres, the rest as written)."""
    u, v = norm_unit(unit), float(value)
    if u in TIME_TO_MIN:
        return v * TIME_TO_MIN[u], "min"
    if u in LENGTH_TO_M:
        return v * LENGTH_TO_M[u], "m"
    return v, u


def fmt_value(v):
    val = v.get("value")
    return f"{val:g} {v.get('unit')}" if isinstance(val, (int, float)) else f"{val} {v.get('unit')}"


def norm_text(s):
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    s = s.replace("–", "-").replace("—", "-").replace("−", "-")
    s = re.sub(r"[*_`|]", " ", s)
    return re.sub(r"\s+", " ", s).strip().lower()


MAX_PAGES = 100000          # no document has more physical pages; larger numbers are typos


def parse_pages(s):
    """Physical pages: '12', '12-15', '12, 14', '11-33 (odd)', '5-8 (to 5.6)'. Returns a set, or None if invalid."""
    s = str(s).strip()
    m = re.match(r"^\s*(\d+(?:\s*[-–]\s*\d+)?(?:\s*,\s*\d+(?:\s*[-–]\s*\d+)?)*)\s*(?:\((.*)\))?\s*$", s)
    if not m:
        return None
    note = (m.group(2) or "").lower()
    pages = set()
    for a, b in re.findall(r"(\d+)(?:\s*[-–]\s*(\d+))?", m.group(1)):
        a, b = int(a), int(b or a)
        if a > b or a < 1 or b > MAX_PAGES:
            return None
        rng = range(a, b + 1)
        if "odd" in note:
            rng = [n for n in rng if n % 2]
        elif "even" in note:
            rng = [n for n in rng if not n % 2]
        pages.update(rng)
    return pages or None


def compress(nums):
    nums = sorted(nums)
    out, start = [], None
    for i, n in enumerate(nums):
        if start is None:
            start = n
        if i == len(nums) - 1 or nums[i + 1] != n + 1:
            out.append(f"{start}" if start == n else f"{start}-{n}"); start = None
    s = ", ".join(out)
    return s if len(s) < 80 else s[:77] + "..."


def valid_date(v):
    if isinstance(v, (dt.date, dt.datetime)):
        return v if isinstance(v, dt.date) and not isinstance(v, dt.datetime) else v.date()
    if isinstance(v, str):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", v)
        if m:
            try:
                return dt.date.fromisoformat(m.group(1))
            except ValueError:
                return None
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


def body_blocks(lines):
    """Split a page body into blocks: ('table'|'fence'|'para'|'blank', [lines]). Tables with or without outer pipes."""
    sep_re = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$")
    i, out = 0, []
    while i < len(lines):
        s = lines[i].strip()
        if s.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            out.append(("fence", lines[i:j + 1])); i = j + 1
        elif s.startswith("|") or ("|" in s and i + 1 < len(lines) and sep_re.match(lines[i + 1])):
            j = i + 2 if not s.startswith("|") else i
            while j < len(lines) and lines[j].strip() and ("|" in lines[j]):
                j += 1
            out.append(("table", lines[i:max(j, i + 1)])); i = max(j, i + 1)
        elif not s:
            out.append(("blank", [lines[i]])); i += 1
        else:
            j = i
            while j < len(lines) and lines[j].strip() and not lines[j].strip().startswith(("|", "```")) \
                    and not (j + 1 < len(lines) and "|" in lines[j] and sep_re.match(lines[j + 1])):
                j += 1
            out.append(("para", lines[i:max(j, i + 1)])); i = max(j, i + 1)
    return out


def is_table(blk):
    return len(blk) >= 2 and bool(re.match(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$", blk[1]))


def blockquotes(body):
    paras, cur = [], []
    for line in body.splitlines() + [""]:
        s = line.strip()
        if s.startswith(">") and s.lstrip("> ").strip():
            cur.append(s.lstrip(">").strip())
        else:
            if cur:
                paras.append(" ".join(cur)); cur = []
    return paras


def sha256(p: Path):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# =====================================================================================================
# 3. Loading a wiki (fails closed: anything unreadable becomes a finding, never a crash or a silent skip)
# =====================================================================================================
DOC_NAMES = {"readme.md", "agents.md", "claude.md", "contributing.md", "changelog.md", "log.md", "spec.md",
             "code_of_conduct.md", "index.md"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".obsidian", ".venv", "venv"}


def read_text(p: Path):
    return p.read_text(encoding="utf-8-sig", errors="replace")


def load_yaml_file(p: Path):
    """(data, error). Missing file -> (None, None)."""
    if not p.exists():
        return None, None
    try:
        return yaml.safe_load(read_text(p)), None
    except yaml.YAMLError as e:
        return None, str(e).replace("\n", " ")[:160]


def norm_rel(s):
    s = str(s or "").replace("\\", "/").strip()
    while s.startswith("./"):
        s = s[2:]
    return os.path.normpath(s).replace("\\", "/") if s else s


class Wiki:
    def __init__(self, root: Path, legacy: bool = False, raw_root=None):
        self.root = Path(root).resolve()
        self.legacy = legacy
        self.raw_root = Path(raw_root).resolve() if raw_root else None
        self.load_errors = []          # (code, path, msg)
        self._raw_cache, self.raw_errors, self._dircache = {}, [], {}
        self.cfg, self.registry, self.sources = {}, [], {}
        self.profiles, self.projects, self.pages = [], [], {}
        self.ignored = []
        self.carried_rows = 0
        self.topic_conflicts = {}
        self.by_stem = collections.defaultdict(list)
        if not self.root.is_dir():
            self.load_errors.append(("E000", str(root), "wiki root not found"))
            return
        cfg, err = load_yaml_file(self.root / "edka.yaml")
        if err:
            self.load_errors.append(("E000", "edka.yaml", err))
        elif cfg is None and not legacy:
            self.load_errors.append(("E000", "edka.yaml", "missing (every EDKA wiki has one; use --legacy for older wikis)"))
        if cfg is not None and not isinstance(cfg, dict):
            self.load_errors.append(("E029", "edka.yaml", "must be a YAML mapping"))
        self.cfg = cfg if isinstance(cfg, dict) else {}
        sanitize(self.cfg, CFG_SCHEMA, "edka.yaml", "E029", self.load_errors)
        self.num_re = build_num_re(self.cfg.get("units") or ())
        reg_name = self.cfg.get("registry", "sources.yaml")
        reg, err = load_yaml_file(self.root / reg_name)
        if err:
            self.load_errors.append(("E000", reg_name, err))
        elif reg is None and not legacy:
            self.load_errors.append(("E000", reg_name, "registry missing"))
        elif reg is not None and not isinstance(reg, list):
            self.load_errors.append(("E014", reg_name, "registry must be a YAML list of sources"))
        self.registry = []
        for i, s in enumerate(reg if isinstance(reg, list) else []):
            if not isinstance(s, dict):
                self.load_errors.append(("E014", reg_name, f"entry {i + 1} is not a mapping")); continue
            sanitize(s, SOURCE_SCHEMA, reg_name, "E014", self.load_errors, f"{s.get('id', i + 1)}: ")
            self.registry.append(s)
        seen = collections.Counter(s.get("id") for s in self.registry if isinstance(s, dict))
        for sid, n in seen.items():
            if n > 1:
                self.load_errors.append(("E014", reg_name, f"duplicate id '{sid}' ({n} entries)"))
        self.sources = {s.get("id"): s for s in self.registry if isinstance(s, dict) and s.get("id")}
        self.has_registry = bool(self.registry)
        for kind, key, store, code in (("profiles", "profiles", self.profiles, "E019"),
                                       ("projects", "projects", self.projects, "E021")):
            d = self.root / self.cfg.get(key, kind)
            if d.is_dir():
                for f in sorted(d.glob("*.y*ml")):
                    data, err = load_yaml_file(f)
                    if err or not isinstance(data, dict):
                        self.load_errors.append((code, self.rel(f), err or "not a YAML mapping"))
                        continue
                    sanitize(data, PROFILE_SCHEMA if kind == "profiles" else PROJECT_SCHEMA, self.rel(f), code, self.load_errors)
                    store.append((f, data))
        skip = {(self.root / self.cfg.get(k, k)).resolve() for k in ("raw", "evidence")}
        ignore = [str(g) for g in (self.cfg.get("ignore") or [])]
        for d, dirs, files in os.walk(self.root):
            dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")
                       and (Path(d) / x).resolve() not in skip]
            for f in files:
                if not f.endswith(".md"):
                    continue
                p = Path(d) / f
                rel = self.rel(p)
                if any(Path(rel).match(g) for g in ignore):
                    self.ignored.append(rel)
                    head = read_text(p)[:400]
                    if re.search(r"(?m)^type:\s*(source-page|topic|coverage|note)\b", head):
                        self.load_errors.append(("E029", rel, "an EDKA page is hidden by edka.yaml ignore:"))
                    continue
                txt = read_text(p)
                m = FM_RE.match(txt)
                fm, err = None, None
                if m:
                    try:
                        fm = yaml.safe_load(m.group(1))
                        if not isinstance(fm, dict):
                            fm, err = None, "frontmatter is not a mapping"
                    except yaml.YAMLError as e:
                        err = str(e).splitlines()[0]
                    except ValueError as e:          # e.g. updated: 2026-02-30
                        err = f"invalid value: {e}"
                body = txt[m.end():] if m else txt
                if fm is not None and not legacy:
                    sanitize(fm, PAGE_SCHEMA, rel, "E029", self.load_errors)
                self.pages[p.resolve()] = {"fm": fm, "err": err, "has_fm": bool(m), "body": body}
        for p in self.pages:
            self.by_stem[p.stem.lower()].append(p)

    # -- helpers
    def rel(self, p):
        try:
            return Path(p).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return str(p)

    def page(self, rel):
        p = (self.root / norm_rel(rel)).resolve()
        return p if p in self.pages else None

    def fm(self, p):
        return (self.pages.get(p) or {}).get("fm") or {}

    def raw_path(self, s):
        name = str((s or {}).get("raw", ""))
        if self.raw_root and (self.raw_root / name).is_file():
            return self.raw_root / name
        return self.root / name

    def raw_text(self, sid, pages=None, normalise=True):
        """Text of a source's raw file, limited to `pages` when the format allows. None if unavailable."""
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
            raw = read_text(rp)
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
                # Some pdftotext builds cannot open non-ASCII paths on Windows: run from the file's folder,
                # or from a temporary ASCII copy when the file name itself is not ASCII.
                tmp = None
                if rp.name.isascii():
                    cwd, name = str(rp.parent), rp.name
                else:
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
        return txt

    def page_type(self, p, fm):
        if fm and fm.get("type") is not None:
            return str(fm.get("type"))
        if not self.legacy:
            return None                      # strict mode: type is required
        rp = self.rel(p).lower()
        if "coverage" in p.stem.lower():
            return "coverage"
        if p.stem.lower() in ("index", "readme", "log") or p.stem.lower().endswith("-index"):
            return "index"
        if rp.startswith("topics/") or "/topics/" in rp:
            return "topic"
        return "source-page"

    def short_names(self):
        names = {}
        for sid, s in self.sources.items():
            short = s.get("short")
            for n in [sid] + ([short] if isinstance(short, str) else list(short or [])):
                names[str(n).lower()] = sid
        return names

    def link_target(self, from_page, link):
        """Resolve a Markdown link or wikilink to a page. Returns (page or None, ambiguous: bool)."""
        link = link.strip()
        if link.endswith(".md") and ("/" in link or (from_page.parent / link).exists()):
            t = (from_page.parent / link).resolve()
            return (t if t in self.pages else None), False
        stem = Path(link).stem.lower() if link.endswith(".md") else Path(link).name.lower()
        hits = self.by_stem.get(stem, [])
        if not hits and "/" in link:
            base = (from_page.parent / link).resolve()
            hits = [x for x in (base.with_suffix(".md"), base / "index.md") if x in self.pages]
        if len(hits) > 1:
            return None, True
        return (hits[0] if hits else None), False


# -----------------------------------------------------------------------------------------------------
# 3b. Types: every YAML field is checked for its type before any check reads it. A wrong type is reported
#     and the field is dropped, so later checks never see malformed data (and never crash on it).
# -----------------------------------------------------------------------------------------------------
def _type_ok(val, kind):
    if kind == "any":
        return True, val
    if kind == "str":
        if isinstance(val, bool) or val is None or isinstance(val, (list, dict)):
            return False, None
        return True, str(val)
    if kind == "int":
        return (isinstance(val, int) and not isinstance(val, bool)), val
    if kind == "num":
        return (isinstance(val, (int, float)) and not isinstance(val, bool)), val
    if kind == "bool":
        return isinstance(val, bool), val
    if kind == "date":
        return (valid_date(val) is not None), val
    if kind == "pages":
        if isinstance(val, int) and not isinstance(val, bool):
            return val > 0, str(val)
        return (isinstance(val, str) and parse_pages(val) is not None), val
    if kind == "strlist":
        if not isinstance(val, list):
            return False, None
        out = []
        for x in val:
            ok, x2 = _type_ok(x, "str")
            if not ok:
                return False, None
            out.append(x2)
        return True, out
    if kind == "str_or_strlist":
        ok, v = _type_ok(val, "str")
        return (True, v) if ok else _type_ok(val, "strlist")
    if kind == "entries":                       # profile lists: ids, or {source, scope}
        if not isinstance(val, list):
            return False, None
        out = []
        for x in val:
            if isinstance(x, dict):
                ok, sid = _type_ok(x.get("source"), "str")
                if not ok:
                    return False, None
                ok2, sc = _type_ok(x.get("scope", ""), "str")
                out.append({"source": sid, "scope": sc if ok2 else ""})
            else:
                ok, sid = _type_ok(x, "str")
                if not ok:
                    return False, None
                out.append(sid)
        return True, out
    if isinstance(kind, dict):
        return isinstance(val, dict), val
    if isinstance(kind, tuple) and kind[0] == "listof":
        return isinstance(val, list), val
    return True, val


def sanitize(obj, schema, where, code, sink, path=""):
    """Check obj (a dict) against schema in place. Bad fields are removed and reported to sink."""
    for key, kind in schema.items():
        if key not in obj:
            continue
        val = obj[key]
        label = f"{path}{key}"
        if isinstance(kind, tuple) and kind[0] == "listof":
            if not isinstance(val, list):
                sink.append((code, where, f"{label} must be a list")); del obj[key]; continue
            keep = []
            for i, el in enumerate(val):
                if not isinstance(el, dict):
                    sink.append((code, where, f"{label}[{i}] must be a mapping")); continue
                sanitize(el, kind[1], where, code, sink, f"{label}[{i}].")
                keep.append(el)
            obj[key] = keep
            continue
        if kind == "verification":
            if isinstance(val, str):
                continue
            if not isinstance(val, dict):
                sink.append((code, where, f"{label} must be a mapping")); del obj[key]; continue
            sanitize(val, VERIF_SCHEMA, where, code, sink, f"{label}.")
            continue
        ok, new = _type_ok(val, kind)
        if not ok:
            kind_name = kind if isinstance(kind, str) else "mapping"
            sink.append(("E001" if kind == "date" else code, where, f"{label}: {val!r:.40} is not a valid {kind_name}"))
            del obj[key]
        else:
            obj[key] = new


VERIF_SCHEMA = {"status": "str", "date": "date", "by": "str", "author": "str", "ref": "str"}
VALUE_SCHEMA = {"key": "str", "value": "num", "unit": "str", "dir": "str", "page": "pages", "locator": "str", "note": "str"}
ENTRY_SCHEMA = {"source": "str", "locators": "strlist", "depth": "str", "reason": "str"}
CONFLICT_SCHEMA = {"id": "str", "between": "strlist", "summary": "str", "status": "str"}
PAGE_SCHEMA = {"type": "str", "title": "str", "source": "str", "source_pages": "pages", "transcription": "str",
               "updated": "date", "verification": "verification", "values": ("listof", VALUE_SCHEMA),
               "sources_covered": ("listof", ENTRY_SCHEMA), "sources_silent": ("listof", ENTRY_SCHEMA),
               "conflicts": ("listof", CONFLICT_SCHEMA), "derived_from": "strlist", "history": "strlist", "author": "str",
               "image_verified": "strlist"}
CFG_SCHEMA = {"level": "str", "registry": "str", "profiles": "str", "projects": "str", "raw": "str", "evidence": "str",
              "ignore": "strlist", "units": "strlist", "excluded_from_topics": "strlist", "edka_version": "str"}
SOURCE_SCHEMA = {"id": "str", "title": "str", "edition": "str", "kind": "str", "raw": "str", "pages": "int",
                 "transcription": "str", "folder": "str", "status": "str", "short": "str_or_strlist", "sha256": "str",
                 "supersedes": "str", "redistributable": "bool", "license_note": "str"}
PROFILE_SCHEMA = {"name": "str", "applies_to": "str", "binding": "entries", "client": "entries",
                  "reference": "entries", "excluded": "entries"}
DECISION_SCHEMA = {"id": "str", "topic": "str", "conflict": "str", "question": "str", "key": "str", "value": "num",
                   "unit": "str", "decision": "str", "basis": "str", "by": "str", "date": "date"}
PROJECT_SCHEMA = {"id": "str", "title": "str", "profile": "str", "decisions": ("listof", DECISION_SCHEMA)}


# =====================================================================================================
# 4. Sources layer: registry, source pages, verbatim quotes, structured values, coverage maps
# =====================================================================================================
def check_registry(w, r, level):
    for s in w.registry:
        if not isinstance(s, dict) or not s.get("id"):
            r.add("E014", "sources.yaml", f"entry without id: {s!r:.80}")
            continue
        sid = s["id"]
        required = ["title", "edition", "kind", "raw", "transcription", "folder", "status"]
        if level in LEVELS and LEVELS.index(level) >= LEVELS.index("coverage"):
            required.append("pages")
        for k in required:
            if k not in s:
                r.add("E014", "sources.yaml", f"{sid}: missing '{k}'")
        if s.get("kind") and s["kind"] not in KINDS:
            r.add("E014", "sources.yaml", f"{sid}: kind '{s['kind']}' not in {KINDS}")
        if s.get("transcription") not in (None, *TRANSCRIPTION):
            r.add("E014", "sources.yaml", f"{sid}: transcription must be verbatim|paraphrase")
        if s.get("status") not in (None, "active", "superseded", "withdrawn"):
            r.add("E014", "sources.yaml", f"{sid}: bad status '{s.get('status')}'")
        if "pages" in s and not (isinstance(s["pages"], int) and s["pages"] > 0):
            r.add("E014", "sources.yaml", f"{sid}: pages must be a positive whole number")
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
            r.add("E007", "sources.yaml", f"{sid}: {s['raw']} changed; re-verify its pages, then `edka hash --force {sid}`")
        folder = w.root / str(s.get("folder", ""))
        if s.get("folder") and not list(folder.glob("*coverage*.md")):
            r.add("W104", s.get("folder"), sid)


def page_pages(w, fm):
    """Set of physical pages of a source page, or None."""
    return parse_pages(fm.get("source_pages", "")) if fm.get("source_pages") is not None else None


def check_source_page(w, p, fm, body, r):
    rp = w.rel(p)
    sid = fm.get("source")
    src = w.sources.get(sid) or {}
    if not w.legacy or w.has_registry:
        for k in ("source", "source_pages"):
            if k not in fm:
                r.add("E002", rp, k)
        if sid and sid not in w.sources:
            r.add("E003", rp, sid)
    elif "source_pages" not in fm and not str(fm.get("verification", "")).lower().startswith("derived"):
        r.add("E002", rp, "source_pages")
    pages = None
    if "source_pages" in fm:
        pages = page_pages(w, fm)
        if pages is None:
            if not w.legacy:
                r.add("E026", rp, f"source_pages '{fm.get('source_pages')}' is not a page list")
        elif src.get("pages") and max(pages) > int(src["pages"]):
            r.add("E026", rp, f"source_pages {compress(pages)} beyond the source's {src['pages']} pages")
    if w.legacy:
        if pages:
            for n in PMARK_RE.findall(body):
                if int(n) not in pages:
                    r.add("W102", rp, f"⟦p.{n}⟧ not in {compress(pages)}")
        return
    if fm.get("transcription") is not None and fm["transcription"] not in TRANSCRIPTION:
        r.add("E029", rp, f"transcription '{fm['transcription']}' (use verbatim|paraphrase)")
    if fm.get("updated") is not None and valid_date(fm["updated"]) is None:
        r.add("E001", rp, f"updated: '{fm['updated']}' is not a valid date")
    check_calc_lines(w, rp, body, r)
    mode = fm.get("transcription") or src.get("transcription")
    if mode == "verbatim":
        check_verbatim(w, rp, sid, pages, body, r)
    if pages:
        raw = w.raw_text(sid, pages, normalise=False)
        if raw is not None:
            is_text = w.raw_path(src).suffix.lower() in (".md", ".txt")   # no OCR to blame for a text source
            on_image = numbers_in("\n".join(fm.get("image_verified") or []), w.num_re)   # checked on the page image
            for n in sorted(numbers_in(body, w.num_re) - numbers_in(raw, w.num_re) - (set() if is_text else on_image)):
                r.add("E031" if is_text else "W116", rp, f"{n} not in raw pages {compress(pages)}")
        for n in PMARK_RE.findall(body):
            if int(n) not in pages:
                r.add("W102", rp, f"⟦p.{n}⟧ not in {compress(pages)}")
    if fm.get("values") is not None:
        check_values(w, rp, fm, body, pages, r)


def check_calc_lines(w, rp, body, r):
    for line in body.splitlines():
        if CALC_MARK in line:
            text = line.replace(CALC_MARK, "")
            text = re.sub(r"\[[^\]]*\]\([^)]*\)|<!--|-->|https?://\S+", " ", text)   # links are not arithmetic
            if not CALC_OK_RE.search(text):
                r.add("E032", rp, line.strip()[:70])
            else:
                r.add("I002", rp, line.strip()[:70])


def check_verbatim(w, rp, sid, pages, body, r):
    quotes = blockquotes(body)
    if not quotes:
        return
    raw = w.raw_text(sid, pages)
    if raw is None:
        r.add("W115", rp, f"{sid}: raw text not available")
        return
    boundary = re.compile(r"[.;:!?](?:\s|$)")
    for q in quotes:
        frags = [norm_text(f) for f in re.split(r"…|\.\.\.", q)]
        frags = [f for f in frags if len(f) >= 3]
        if not frags:
            continue
        missing = [f for f in frags if f not in raw]
        if missing:
            r.add("E016", rp, f'not in raw: "{missing[0][:70]}"')
            continue
        m = re.search("(.*?)".join(re.escape(f) for f in frags), raw, re.S)
        if not m:
            r.add("E016", rp, f'fragments out of order: "{q[:70]}"')
            continue
        # A cut may drop whole sentences. Inside a sentence the quote keeps part of, it must not drop a negation:
        # check the rest of the sentence the previous fragment ends in, and the start of the sentence the next
        # fragment begins in. Whole sentences in between are not checked.
        for i, gap in enumerate(m.groups()):
            parts = boundary.split(gap)
            ends_sentence = bool(re.search(r"[.;:!?]$", frags[i].rstrip()))
            if len(parts) == 1:
                pieces = [gap]
            else:
                pieces = ([] if ends_sentence else [parts[0]]) + [parts[-1]]
            neg = next((NEGATION_RE.search(x) for x in pieces if NEGATION_RE.search(x)), None)
            if neg:
                r.add("E016", rp, f'the ellipsis drops "{neg.group(0)}" inside a quoted sentence: "{q[:70]}"')
                break


def check_values(w, rp, fm, body, pages, r):
    stated = numbers_in(body, w.num_re)
    keys = collections.Counter()
    for v in fm.get("values") or []:
        if not (isinstance(v, dict) and v.get("key") and isinstance(v.get("value"), (int, float))
                and not isinstance(v.get("value"), bool) and v.get("unit") and v.get("dir") in VALUE_DIRS):
            r.add("E022", rp, json.dumps(v, ensure_ascii=False, default=str)[:90]); continue
        keys[v["key"]] += 1
        if f"{float(v['value']):g} {norm_unit(v['unit'])}" not in stated:
            r.add("E023", rp, f"{v['key']} = {fmt_value(v)}")
        vp = parse_pages(v["page"]) if v.get("page") is not None else None
        if pages and vp and not vp <= pages:
            r.add("W102", rp, f"value {v['key']} page {v['page']} not in {compress(pages)}")
    for k, n in keys.items():
        if n > 1:
            r.add("W124", rp, f"{k} ({n} entries)")


def page_values(w, page):
    fm = w.fm(page)
    out, seen = [], set()
    for v in fm.get("values") or []:
        if isinstance(v, dict) and v.get("key") and isinstance(v.get("value"), (int, float)) \
                and not isinstance(v.get("value"), bool) and v.get("unit") and v.get("dir") in VALUE_DIRS:
            if v["key"] in seen:            # duplicate key on one page: first entry wins (W124 reports it)
                continue
            seen.add(v["key"])
            out.append({**v, "sid": fm.get("source"), "page_path": page, "base": base_value(v["value"], v["unit"])})
    return out


def check_coverage(w, p, fm, body, r):
    rp = w.rel(p)
    sid = (fm or {}).get("source")
    src = w.sources.get(sid)
    if src is None:
        for s in w.sources.values():
            if s.get("folder") and (w.root / s["folder"]).resolve() == p.parent.resolve():
                src = s; break
    default_total = (src or {}).get("pages")
    groups = collections.OrderedDict()
    current = "main"
    groups[current] = {"total": default_total, "rows": []}
    lines = [l.strip() for l in body.splitlines()]
    is_sep = lambda s: s.startswith("|") and set(s) <= set("|-: ")
    page_col = None
    mapped_to = collections.defaultdict(set)      # wiki page -> physical pages mapped to it
    file_pages_re = re.compile(r"\((\d+)\s*p\.?\)|\b(\d+)\s*pp\b")
    for i, s in enumerate(lines):
        if s.startswith("#"):
            m = file_pages_re.search(s)
            current = s.lstrip("# ")[:70]
            groups.setdefault(current, {"total": (int(m.group(1) or m.group(2)) if m else None), "rows": []})
            continue
        if not s.startswith("|") or is_sep(s):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if (i == 0 or not lines[i - 1].startswith("|")) and i + 1 < len(lines) and is_sep(lines[i + 1]):
            page_col = next((k for k, c in enumerate(cells[:3]) if re.search(r"\b(pages?|pp)\b", c, re.I)), None)
            continue
        if page_col is None or page_col >= len(cells):
            continue
        pages = parse_pages(cells[page_col])
        if not pages:
            if not w.legacy and cells[page_col].strip():
                r.add("E008", rp, f"page cell '{cells[page_col][:30]}' is not a page list (or exceeds {MAX_PAGES})")
            continue
        if page_col > 0 and cells[0] and re.search(r"\.(pdf|docx?|xlsx?|txt|md)\b|\(\d+\s*pp?\.?\)", cells[0], re.I):
            current = cells[0]
            m = file_pages_re.search(cells[0])
            groups.setdefault(current, {"total": (int(m.group(1) or m.group(2)) if m else None), "rows": []})
        treat = cells[-1]
        groups.setdefault(current, {"total": None, "rows": []})["rows"].append(pages)
        head = re.split(r"[:\s(]", treat.strip("*`").lower(), 1)[0]
        if not w.legacy and head not in TREATMENTS:
            r.add("W111", rp, treat[:50])
        links = MDLINK_RE.findall(" ".join(cells[:-1]))
        if head in CARRIED:
            w.carried_rows += 1
        if not w.legacy and head in CARRIED and not links:
            r.add("E008", rp, f"pages {compress(pages)} are '{head}' but no wiki page is linked")
        for l in links:
            t = (p.parent / l).resolve()
            mapped_to[t] |= pages
    if not w.legacy and not any(info["rows"] for info in groups.values()):
        r.add("E008", rp, "no coverage table found (a table with a 'Pages' column and one row per page range)")
    carried_any = False
    for g, info in groups.items():
        rows = info["rows"]
        if not rows:
            continue
        where = collections.defaultdict(list)
        for pages in rows:
            lo, hi = min(pages), max(pages)
            multi = hi > lo
            for n in pages:
                where[n].append(multi and n in (lo, hi))
        # A page may be shared by rows when it is an end page of each multi-page row (a clause split mid-page).
        dup = sorted(n for n, occ in where.items() if len(occ) > 1 and not all(occ))
        lo = 1 if info["total"] else min(where)
        hi = info["total"] or max(where)
        parities = {n % 2 for n in where}
        missing = [n for n in range(lo, hi + 1) if n not in where and (len(parities) == 2 or n % 2 in parities)]
        for label, pages in (("not mapped", missing), ("mapped twice", dup)):
            if pages:
                r.add("W112" if w.legacy else "E008", rp, f"{g}: pages {compress(pages)} {label}")
        if info["total"] and max(where) > info["total"]:
            r.add("W112" if w.legacy else "E008", rp, f"{g}: maps page {max(where)} but source has {info['total']}")
    if not w.legacy and src:
        for page, pg in w.pages.items():
            f = pg["fm"] or {}
            if f.get("type") == "source-page" and f.get("source") == src.get("id"):
                pp = page_pages(w, f)
                if pp and not pp <= mapped_to.get(page, set()):
                    r.add("W125", w.rel(page), f"pages {compress(pp - mapped_to.get(page, set()))} not mapped to it in {rp}")


# =====================================================================================================
# 5. Topics layer: neutral synthesis, attribution of every number, negative evidence, conflicts
# =====================================================================================================
# A column whose header is a verdict (exact match after removing punctuation) is an error;
# prose that sounds like a verdict is a warning, because neutral text can use the same words.
VERDICT_HEADERS = {"binding", "binding here", "is binding", "applies", "applies here", "applicable here", "governs",
                   "governs here", "governing", "use", "use here", "use it", "verdict", "answer", "decision",
                   "applies to this project", "required here", "mandatory here"}
APPLICABILITY_ERROR_RE = re.compile(r"\b(under profile|governs here|binding here|applies here|the answer is)\b", re.I)
APPLICABILITY_PROSE_RE = re.compile(
    r"\b(designers? (?:must|should) (?:use|follow|apply) the|(?:use|follow|apply) the [\w-]+ (?:value|code|standard|guide) and"
    r"|ignore the (?:code|guide|standard|other)|in [A-Z][\w-]+, (?:use|apply|follow) the)\b")


def source_ids(entries):
    return [e["source"] for e in entries or [] if isinstance(e, dict) and e.get("source")]


def row_pages(w, topic, row, r=None, rp=None):
    """Source pages a table row links to. Ambiguous wikilinks are reported (W122) and ignored."""
    out = []
    for l in MDLINK_RE.findall(row):
        t = (topic.parent / l).resolve()
        if t in w.pages:
            out.append(t)
    for l in WIKILINK_RE.findall(row):
        t, amb = w.link_target(topic, l)
        if amb and r is not None:
            r.add("W122", rp, f"[[{l.strip()}]]")
        if t:
            out.append(t)
    return [t for t in dict.fromkeys(out) if w.fm(t).get("source")]


def row_sources(w, topic, row):
    return list(dict.fromkeys(w.fm(t).get("source") for t in row_pages(w, topic, row)))


def check_topic(w, p, fm, body, r):
    rp = w.rel(p)
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
                    r.add("W105", rp, f"silent {e['source']} ({e['depth']})")
            elif e.get("depth") and e["depth"] not in DEPTHS:
                r.add("E009", rp, f"sources_covered depth '{e['depth']}'")
            elif e.get("depth") in ("index", "not-opened"):
                r.add("W105", rp, f"covered {e.get('source')} ({e['depth']})")
    if w.legacy:
        check_conflicts(w, rp, fm, r)
        return
    both = set(source_ids(cov)) & set(source_ids(sil))
    for sid in sorted(both):
        r.add("E030", rp, sid)
    if fm.get("updated") is not None and valid_date(fm["updated"]) is None:
        r.add("E001", rp, f"updated: '{fm['updated']}' is not a valid date")

    # every source the topic relies on: listed, derived from, or linked from a table row
    derived = []
    for d in fm.get("derived_from") or []:
        dp = w.page(d)
        if dp is None:
            r.add("E005", rp, f"derived_from: {d}")
        else:
            derived.append(dp)
    blocks = body_blocks(body.splitlines())
    rows = []                                    # (row text, [source pages])
    for kind, blk in blocks:
        if kind == "table" and is_table(blk):
            for row in blk[2:]:
                rows.append((row, row_pages(w, p, row, r, rp)))
    used = set(source_ids(cov)) | {w.fm(d).get("source") for d in derived} | {w.fm(t).get("source") for _, ts in rows for t in ts}
    used.discard(None)
    for sid in sorted(used):
        st = (w.sources.get(sid) or {}).get("status")
        if st == "withdrawn":
            r.add("W107", rp, sid)
        elif st == "superseded" and sid not in (fm.get("history") or []):
            r.add("W108", rp, sid)
    for sid in sorted(used & set(w.cfg.get("excluded_from_topics") or [])):
        r.add("E012", rp, sid)
    row_used = {w.fm(t).get("source") for _, ts in rows for t in ts} | {w.fm(d).get("source") for d in derived}
    row_used.discard(None)
    silent = set(source_ids(sil))
    history = set(fm.get("history") or [])
    for sid in sorted(history):
        if (w.sources.get(sid) or {}).get("status") not in ("superseded", "withdrawn"):
            r.add("E029", rp, f"history: '{sid}' is not superseded or withdrawn (history is only for old editions)")
    history = {s for s in history if (w.sources.get(s) or {}).get("status") in ("superseded", "withdrawn")}
    table_used = {w.fm(t).get("source") for _, ts in rows for t in ts}
    for sid in sorted(table_used & silent):
        r.add("E030", rp, f"{sid} is listed as silent but the page reports its content")
    for sid in sorted(row_used - set(source_ids(cov)) - silent - history):
        r.add("E033", rp, sid)
    relevant = {sid for _, prof in w.profiles for k in ("binding", "client") for sid in profile_ids(prof, k)}
    for sid, s in sorted(w.sources.items()):
        if sid in relevant and s.get("status", "active") == "active" and sid not in used | silent | history:
            r.add("W130", rp, sid)
    check_calc_lines(w, rp, body, r)

    # neutrality
    names = w.short_names()
    for kind, blk in blocks:
        if kind == "table" and is_table(blk):
            for cell in blk[0].strip().strip("|").split("|"):
                if re.sub(r"[^a-z ]", "", cell.lower()).strip() in VERDICT_HEADERS:
                    r.add("E018", rp, f"column '{cell.strip()}'")
        elif kind == "para" and not blk[0].lstrip().startswith("#"):
            text = SRC_TAG_RE.sub("", "\n".join(blk))
            m = APPLICABILITY_ERROR_RE.search(text)
            if m:
                r.add("E018", rp, f'"{m.group(0)}" in: {blk[0].strip()[:50]}')
            else:
                m = APPLICABILITY_PROSE_RE.search(text)
                if m:
                    r.add("W127", rp, f'"{m.group(0)}" in: {blk[0].strip()[:50]}')
            tagged = {x.strip() for t in SRC_TAG_RE.findall("\n".join(blk)) for x in t.split(",")}
            low = text.lower()
            named = {sid for n, sid in names.items() if re.search(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", low)}
            if named - tagged:
                r.add("W120", rp, f"{', '.join(sorted(named - tagged))}: \"{blk[0].strip()[:50]}\"")

    # attribution of numbers: each row against the pages it links; prose and frontmatter against all derived pages
    union = set().union(*(numbers_in(w.pages[d]["body"], w.num_re) for d in derived)) if derived else set()
    for row, pages in rows:
        nums = numbers_in(row, w.num_re)
        if not pages:
            if nums:                      # a row that reports values must say whose values they are
                r.add("W119", rp, row.strip()[:60])
            for n in sorted(nums - union):
                r.add("E015", rp, f"{n} (row has no source link and no derived page states it)")
            continue
        known = set().union(*(numbers_in(w.pages[t]["body"], w.num_re) for t in pages))
        for n in sorted(nums - known):
            srcs = ", ".join(sorted({w.fm(t).get('source') for t in pages}))
            r.add("E015", rp, f"{n} not on the linked page of {srcs}: {row.strip()[:50]}")
    prose = "\n".join("\n".join(blk) for kind, blk in blocks if kind == "para")
    for n in sorted(numbers_in(prose, w.num_re) - union):
        r.add("E015", rp, f"{n} in prose, not on any derived_from page")
    fm_text = "\n".join(str(c.get("summary", "")) for c in fm.get("conflicts") or [] if isinstance(c, dict))
    for n in sorted(numbers_in(fm_text, w.num_re) - union):
        r.add("E015", rp, f"{n} in a conflict summary, not on any derived_from page")

    # staleness
    tdate = valid_date(fm.get("updated"))
    for dp in derived:
        ddate = valid_date(w.fm(dp).get("updated"))
        if tdate and ddate and ddate > tdate:
            r.add("W101", rp, f"{w.rel(dp)} updated {ddate} > topic {tdate}")
    pairs = set()
    for c in fm.get("conflicts") or []:
        if isinstance(c, dict) and isinstance(c.get("between"), list):
            for a in c["between"]:
                for b in c["between"]:
                    pairs.add((a, b))
    for key, vals in topic_values(w, fm).items():
        if len(vals) > 1 and not comparable(vals) and any(v["dir"] != "info" for v in vals):
            r.add("W121", rp, f"{key}: " + ", ".join(f"{v['sid']} {fmt_value(v)} ({v['dir']})" for v in vals))
            continue
        for i, a in enumerate(vals):
            for b in vals[i + 1:]:
                if a["sid"] == b["sid"] or a["sid"] in history or b["sid"] in history:
                    continue
                if a["base"] != b["base"] and (a["sid"], b["sid"]) not in pairs:
                    r.add("W129", rp, f"{key}: {a['sid']} {fmt_value(a)} vs {b['sid']} {fmt_value(b)}")
    check_conflicts(w, rp, fm, r)


def check_conflicts(w, rp, fm, r):
    for c in fm.get("conflicts") or []:
        if not isinstance(c, dict) or not c.get("id") or c.get("status") not in CONFLICT_STATUS \
                or not isinstance(c.get("between"), list) or len(c["between"]) < 2:
            r.add("E010", rp, json.dumps(c, ensure_ascii=False, default=str)[:100]); continue
        unknown = [s for s in c["between"] if w.has_registry and s not in w.sources]
        if unknown:
            r.add("E003", rp, f"conflict {c['id']}: {', '.join(map(str, unknown))}")
        w.topic_conflicts[(rp, c["id"])] = c["status"]
        if c["status"] == "resolved-by-profile":
            per = {prof.get("name", pp.stem): governing(prof, c["between"])[0] for pp, prof in w.profiles}
            if not any(g not in (None, "n/a") for g in per.values()):
                r.add("E011", rp, f"{c['id']}: no profile makes a side binding")
            for name, g in per.items():
                if g is None:
                    r.add("W118", rp, f"{c['id']} under '{name}'")


def topic_values(w, fm):
    by = collections.OrderedDict()
    for d in fm.get("derived_from") or []:
        dp = w.page(d)
        if dp:
            for v in page_values(w, dp):
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


# =====================================================================================================
# 6. Profiles layer: applicability per jurisdiction
# =====================================================================================================
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
        ids = profile_ids(prof or {}, key)
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
    """Which side of a conflict governs under a profile: (source id | 'n/a' | None, explanation)."""
    excluded = [s for s in between if applicability(prof, s)[0] == "excluded"]
    if len(between) - len(excluded) < 2:
        return "n/a", f"not applicable here: {', '.join(excluded)} excluded by this profile"
    binding = sorted(((applicability(prof, s)[1], s) for s in between if applicability(prof, s)[0] == "binding"),
                     key=lambda x: x[0])
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


def check_profiles(w, r):
    names = collections.Counter(prof.get("name", pp.stem) for pp, prof in w.profiles)
    for n, c in names.items():
        if c > 1:
            r.add("E019", "profiles/", f"profile name '{n}' used by {c} files")
    for pp, prof in w.profiles:
        seen = collections.Counter()
        for key in PROFILE_LISTS:
            for sid in profile_ids(prof, key):
                seen[sid] += 1
                if key != "excluded" and w.has_registry and sid not in w.sources:
                    r.add("E019", w.rel(pp), f"{key}: unknown source '{sid}'")
                st = (w.sources.get(sid) or {}).get("status")
                if key in ("binding", "client") and st == "withdrawn":
                    r.add("E019", w.rel(pp), f"{key}: '{sid}' is withdrawn")
                elif key == "binding" and st == "superseded":
                    r.add("W131", w.rel(pp), sid)
        for sid, n in seen.items():
            if n > 1:
                r.add("E019", w.rel(pp), f"'{sid}' is listed {n} times")


def requirement(prof, vals):
    """The value that applies under a profile: the highest-precedence binding value, raised by any stricter
    client value. Returns (value dict, explanation) or (None, None)."""
    usable = [v for v in vals if v["dir"] != "info"]
    binding = sorted((v for v in usable if applicability(prof, v["sid"])[0] == "binding"),
                     key=lambda v: applicability(prof, v["sid"])[1])
    client = [v for v in usable if applicability(prof, v["sid"])[0] == "client"]
    if not binding and not client:
        return None, None
    req = binding[0] if binding else strictest(client)
    why = f"{req['sid']} {fmt_value(req)}"
    for c in client:
        if c["base"][1] == req["base"][1] and stricter(c["base"][0], req["base"][0], req["dir"]):
            req, why = c, f"client {c['sid']} {fmt_value(c)} (stricter than the binding value)"
    return req, why


# =====================================================================================================
# 7. Projects layer: recorded decisions, never below the code
# =====================================================================================================
def project_decisions(project, topic_rel):
    return [d for d in (project or {}).get("decisions") or []
            if isinstance(d, dict) and norm_rel(d.get("topic")) == topic_rel]


def check_projects(w, r):
    prof_by_name = {prof.get("name", pp.stem): prof for pp, prof in w.profiles}
    decided = set()
    for jp, pj in w.projects:
        jr = w.rel(jp)
        if not pj.get("id"):
            r.add("E021", jr, "missing id")
        prof = prof_by_name.get(pj.get("profile"))
        if prof is None:
            r.add("E021", jr, f"unknown profile '{pj.get('profile')}'")
        for d in pj.get("decisions") or []:
            if not isinstance(d, dict):
                r.add("E021", jr, repr(d)[:60]); continue
            did = d.get("id", "?")
            for k in ("id", "topic", "decision", "basis", "date"):
                if not d.get(k):
                    r.add("E021", jr, f"{did}: missing '{k}'")
            if d.get("date") is not None and valid_date(d["date"]) is None:
                r.add("E021", jr, f"{did}: date '{d['date']}' is not valid")
            topic = norm_rel(d.get("topic"))
            tp = w.page(topic) if topic else None
            if topic and tp is None:
                r.add("E021", jr, f"{did}: unknown topic '{d.get('topic')}'"); continue
            if d.get("key") is not None and tp is not None:
                vals = topic_values(w, w.fm(tp)).get(d["key"], [])
                if not vals:
                    r.add("E021", jr, f"{did}: no source value with key '{d['key']}' on {topic}")
                elif prof is not None and isinstance(d.get("value"), (int, float)) and d.get("unit"):
                    req, why = requirement(prof, vals)
                    if req is not None:
                        mine = base_value(d["value"], d["unit"])
                        if mine[1] != req["base"][1]:
                            r.add("E021", jr, f"{did}: unit {d['unit']} cannot be compared with {req['unit']}")
                        elif stricter(req["base"][0], mine[0], req["dir"]):
                            r.add("E024", jr, f"{did}: {d['key']} {d['value']:g} {d['unit']} is weaker than {why} ({req['dir']})")
            if d.get("key") is None and numbers_in(str(d.get("decision", "")), w.num_re):
                r.add("W132", jr, f"{did}: {str(d.get('decision'))[:50]}")
            if d.get("conflict") and tp is not None:
                if (topic, d["conflict"]) not in w.topic_conflicts:
                    r.add("E021", jr, f"{did}: no conflict '{d['conflict']}' in {topic}")
                decided.add((topic, d["conflict"]))
    for (topic, cid), st in w.topic_conflicts.items():
        if st == "resolved-by-project" and (topic, cid) not in decided:
            r.add("E020", topic, cid)


# =====================================================================================================
# 8. Evidence and verification
# =====================================================================================================
CLOSED_STATUS = {"fixed", "resolved", "rejected", "closed", "corrected", "withdrawn", "not-an-error"}
NO_FINDING_RE = re.compile(r"^\s*(no (discrepanc\w*|issues?|errors?|findings?|differences?)( found)?|none( found)?|nothing (found|to report))\.?\s*$", re.I)
NOT_CHECKED_ALL_RE = re.compile(r"\b(all|any|the) (numbers|values|tables|formulas)\b|\beverything\b|\bnothing (was )?checked\b", re.I)


def name_key(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def check_verification(w, p, fm, ptype, r):
    v = fm.get("verification")
    rp = w.rel(p)
    if v is None:
        if ptype in ("source-page", "topic", "note"):
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
            if not (w.root / path).exists() and not (w.root.parent / path).exists() \
                    and not list((w.root.parent / path).parent.glob(Path(path).name + "*")):
                r.add("W109", rp, path)
        return st
    if not isinstance(v, dict):
        r.add("E004", rp, repr(v)[:70]); return None
    st = v.get("status")
    if st not in VER_STATUS:
        r.add("E004", rp, str(st)); return None
    if v.get("date") is not None and valid_date(v["date"]) is None:
        r.add("E001", rp, f"verification.date '{v['date']}' is not a valid date")
    independent = st in ("independent", "independent-partial")
    if independent and not all(v.get(k) for k in ("date", "by", "ref")):
        r.add("E013", rp, st)
    if independent:
        author = v.get("author") or fm.get("author")
        if not author:
            r.add("W114", rp)
        elif v.get("by") and name_key(author) == name_key(v["by"]):
            r.add("E017", rp, f"author '{author}' and verifier '{v['by']}'")
        elif v.get("by") and (name_key(v["by"]).rstrip("0123456789").startswith(name_key(author)) or
                              name_key(author).rstrip("0123456789").startswith(name_key(v["by"]))):
            r.add("W126", rp, f"author '{author}', verifier '{v['by']}'")
    if st in ("sample-audit", "author-checked") and not v.get("date"):
        r.add("E002", rp, f"verification.date for {st}")
    if v.get("ref"):
        ref = (w.root / str(v["ref"]))
        if not ref.exists():
            r.add("E027" if independent else "W109", rp, f"ref {v['ref']} not found")
        elif independent:
            check_evidence(w, rp, fm, v, ref, r)
    if st == "derived" and not fm.get("derived_from"):
        r.add("W110", rp)
    return st


def check_evidence(w, rp, fm, v, ref, r):
    """An independent claim needs a JSON report naming this source, the pages checked (covering this page), the
    verifier (`by`) and what was not checked, with every finding closed and no 'values not checked'."""
    sid, pages = fm.get("source"), page_pages(w, fm)
    if ref.suffix.lower() != ".json":
        r.add("E027", rp, f"{v['ref']}: an independent claim needs a JSON report (SPEC.md section 4.4)"); return
    try:
        data = json.loads(read_text(ref))
    except ValueError as e:
        r.add("E027", rp, f"{v['ref']} is not valid JSON ({e})"); return
    entries = data.get("reports") if isinstance(data, dict) and isinstance(data.get("reports"), list) else [data]
    entries = [e for e in entries if isinstance(e, dict)]
    match = [e for e in entries if e.get("source") == sid] if sid else []
    if not match:
        r.add("E027", rp, f"{v['ref']} has no entry for source {sid or rp}"); return
    e = match[0]
    pc = e.get("pages_checked", e.get("pages"))
    if not isinstance(pc, list):
        r.add("E027", rp, f"{v['ref']}: pages_checked must be a list of pages"); pc = []
    checked = set()
    for x in pc:
        ps = parse_pages(x) if isinstance(x, (int, str)) and not isinstance(x, bool) else None
        if ps is None:
            r.add("E027", rp, f"{v['ref']}: pages_checked entry {x!r:.30} is not a page"); continue
        checked |= ps
    if pages and checked:
        if v.get("status") == "independent" and not pages <= checked:
            r.add("E027", rp, f"report checked pages {compress(checked)}, page covers {compress(pages)}")
        elif not (pages & checked):
            r.add("E027", rp, f"report checked pages {compress(checked)}, not {compress(pages)}")
    elif pages and not checked:
        r.add("E027", rp, f"{v['ref']}: no pages checked")
    verifier = e.get("verifier")
    if not isinstance(verifier, str) or not verifier.strip():
        r.add("E027", rp, f"{v['ref']}: verifier must be a name")
    elif v.get("by") and name_key(verifier) not in name_key(v["by"]) and name_key(v["by"]) not in name_key(verifier):
        r.add("E027", rp, f"report names verifier '{verifier}', page says '{v['by']}'")
    nc = e.get("not_checked")
    if not isinstance(nc, list):
        r.add("E027", rp, f"{v['ref']}: not_checked must be a list (use [] if everything was checked)")
    elif any(NOT_CHECKED_ALL_RE.search(str(x)) for x in nc):
        r.add("E027", rp, f"report says the values were not checked: {nc}")
    findings = e.get("findings", [])
    if not isinstance(findings, list):
        r.add("E027", rp, f"{v['ref']}: findings must be a list"); findings = []
    open_findings = []
    for f in findings:
        if isinstance(f, dict):
            if str(f.get("status", "")).lower() not in CLOSED_STATUS:
                open_findings.append(f)
        elif not (isinstance(f, str) and NO_FINDING_RE.search(f)):
            open_findings.append(f)
    if open_findings:
        r.add("E027", rp, f"report has {len(open_findings)} open finding(s); give each a status ({', '.join(sorted(CLOSED_STATUS))}) once handled")


# =====================================================================================================
# 9. Links
# =====================================================================================================
def case_mismatch(w, target: Path):
    """True if the path exists but a component's letter case differs from the file system."""
    try:
        rel = target.relative_to(w.root)
    except ValueError:
        return False
    cur = w.root
    for part in rel.parts:
        names = w._dircache.get(cur)
        if names is None:
            try:
                names = w._dircache[cur] = set(os.listdir(cur))
            except OSError:
                return False
        if part not in names:
            return True
        cur = cur / part
    return False


def check_links(w, r):
    inbound = collections.Counter()
    for p, pg in w.pages.items():
        if p.stem.lower() == "log":  # history: old links are expected to rot
            continue
        text = FENCE_RE.sub("", pg["body"])
        for l in WIKILINK_RE.findall(text):
            l = l.strip()
            if "..." in l or not l:
                continue
            t, amb = w.link_target(p, l)
            if t:
                inbound[t] += 1
            elif amb:
                inbound.update(w.by_stem.get(Path(l).stem.lower(), []))
            else:
                r.add("E005", w.rel(p), f"[[{l}]]")
        for raw_link in MDLINK_RE.findall(text):
            if re.match(r"^[a-z]+://", raw_link):
                continue
            t = (p.parent / raw_link).resolve()
            if t in w.pages:
                inbound[t] += 1
                if not w.legacy and case_mismatch(w, Path(os.path.normpath(p.parent / raw_link))):
                    r.add("W123", w.rel(p), raw_link)
            elif not t.exists():
                r.add("E005", w.rel(p), raw_link)
    for p in w.pages:
        stem = p.stem.lower()
        if inbound[p] == 0 and w.fm(p).get("type") != "index" and p.name.lower() not in DOC_NAMES and "coverage" not in stem \
                and not stem.endswith("-index") and not (w.legacy and p.stem.isupper()):
            r.add("W103", w.rel(p))


# =====================================================================================================
# 10. Conformance levels and the validate run
# =====================================================================================================
def check_level(w, r, level):
    if level not in LEVELS:
        r.add("E028", "edka.yaml", f"level '{level}' (use {' | '.join(LEVELS)})"); return
    i = LEVELS.index(level)
    fms = [pg["fm"] or {} for pg in w.pages.values()]
    types = collections.Counter(f.get("type") for f in fms)
    if not w.sources:
        r.add("E028", "sources.yaml", f"level {level} needs at least one registered source")
    if i >= LEVELS.index("synthesis") and types["topic"] == 0:
        r.add("E028", "topics/", f"level {level} needs at least one topic page")
    if i >= LEVELS.index("governed"):
        if not w.profiles:
            r.add("E028", "profiles/", "level governed needs at least one applicability profile")
        statuses = [(f.get("verification") or {}).get("status") if isinstance(f.get("verification"), dict) else None
                    for f in fms if f.get("type") == "source-page"]
        if statuses and not any(s in ("independent", "independent-partial") for s in statuses):
            r.add("E028", "sources/", "level governed needs independent verification (with a report) of at least one source page")
        for p, pg in w.pages.items():
            f = pg["fm"] or {}
            st = (f.get("verification") or {}).get("status") if isinstance(f.get("verification"), dict) else None
            if f.get("type") == "source-page" and st in (None, "unverified"):
                r.add("E028", w.rel(p), "level governed: source page is unverified")
        if w.carried_rows == 0 and w.sources:
            r.add("E028", "sources/", "level governed: no coverage map carries any page (all pending or skipped)")
    r.promoted |= LEVEL_PROMOTE[level]


def validate(root, legacy=False, raw_root=None, strict=False):
    w = Wiki(root, legacy, raw_root)
    r = Report()
    stats = collections.Counter()
    for code, path, msg in w.load_errors:
        r.add(code, path, msg)
    if any(c == "E000" for c, _, _ in w.load_errors) and not w.pages:
        stats["pages"] = 0
        return w, r, stats
    level = str(w.cfg.get("level", "core" if not legacy else "")) if not legacy else None
    if w.sources or not legacy:
        check_registry(w, r, level or "core")
    for p, pg in w.pages.items():
        rp = w.rel(p)
        fm = pg["fm"]
        if pg["err"]:
            r.add("E001", rp, pg["err"]); continue
        name = p.name.lower()
        if fm is None:
            if name in DOC_NAMES or (legacy and (p.stem.isupper() or ".bak" in name)):
                continue
            ptype = w.page_type(p, None)
            if ptype == "coverage":
                check_coverage(w, p, {}, pg["body"], r)
            elif ptype != "index":
                r.add("E001", rp, "no frontmatter")
            continue
        if legacy and (p.stem.isupper() or ".bak" in name):
            continue
        ptype = w.page_type(p, fm)
        if ptype is None:
            r.add("E002", rp, "type"); continue
        if ptype not in PAGE_TYPES:
            r.add("E025", rp, f"type '{ptype}'"); continue
        stats["type:" + ptype] += 1
        if ptype == "index":
            continue
        if ptype == "coverage":
            check_coverage(w, p, fm, pg["body"], r); continue
        st = check_verification(w, p, fm, ptype, r)
        stats["verification:" + str(st)] += 1
        if ptype == "source-page":
            check_source_page(w, p, fm, pg["body"], r)
        elif ptype == "topic":
            check_topic(w, p, fm, pg["body"], r)
            stats["topic:sources_silent_entries"] += len(fm.get("sources_silent") or [])
        elif ptype == "note" and fm.get("updated") is not None and valid_date(fm["updated"]) is None:
            r.add("E001", rp, f"updated: '{fm['updated']}' is not a valid date")
    check_links(w, r)
    check_profiles(w, r)
    check_projects(w, r)
    for e in dict.fromkeys(w.raw_errors):
        r.add("W117", "sources.yaml", e)
    if w.ignored:
        r.add("I003", "edka.yaml", f"{len(w.ignored)} file(s) ignored")
    if level is not None:
        check_level(w, r, level)
    if strict:
        r.promoted |= {k for k in r.items if k.startswith("W") and k not in HEURISTIC}
    stats["pages"] = len(w.pages)
    return w, r, stats


def print_report(w, r, stats, maxn, level=None):
    print(f"EDKA {__version__} validate  root={w.root}  mode={'legacy' if w.legacy else 'strict'}  "
          f"level={w.cfg.get('level', '-')}  registry={len(w.sources)} sources  profiles={len(w.profiles)}  "
          f"projects={len(w.projects)}")
    print("pages:", stats.get("pages", 0), " ", ", ".join(f"{k}={v}" for k, v in sorted(stats.items()) if k != "pages"))
    for code in sorted(r.items, key=lambda c: (not r.is_error(c), c)):
        items = r.items[code]
        tag = " (error at this level)" if code.startswith("W") and r.is_error(code) else ""
        print(f"\n{code} x{len(items)}  {CODES.get(code, ('', ''))[0]}{tag}")
        for it in items[:maxn]:
            print(f"   {it['path']}  {it['msg']}")
        if len(items) > maxn:
            print(f"   ... {len(items) - maxn} more")
    print(f"\nRESULT: {r.errors()} error(s), {r.warnings()} warning(s)   (edka explain <CODE> for how to fix)")


# =====================================================================================================
# 11. Views and answers
# =====================================================================================================
ORDER = {"binding": 0, "client": 1, "reference": 2, "not-listed": 3, "excluded": 4}
LABEL = {"binding": "**Binding**", "client": "Client", "reference": "Reference", "not-listed": "Not in profile"}
LINK_TARGET_RE = re.compile(r"\]\(([^)\s#]+)(#[^)]*)?\)")


def find_profile(w, name):
    for pp, prof in w.profiles:
        if name in (prof.get("name"), pp.stem):
            return prof
    sys.exit(f"edka: no profile '{name}' (have: {', '.join(prof.get('name', pp.stem) for pp, prof in w.profiles) or 'none'})")


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


def render_view(w, topic_path, prof, project=None, out_dir=None):
    topic_path = Path(topic_path).resolve()
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
    gov = sorted(((applicability(prof, s)[1], s) for s in covered if applicability(prof, s)[0] == "binding"),
                 key=lambda x: x[0])
    out.append("## What governs")
    if gov:
        for rank, s in gov:
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
            out.append(f"- **{c.get('id')}** ({' vs '.join(map(str, c.get('between') or []))}): {note}. {c.get('summary', '')}")
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
            out += [f"**{key}**", "", "| Source | Applies here | Value | Page | |", "|---|---|---|---|---|"]
            comp = comparable(shown) if shown else False
            best = strictest(shown) if comp else None
            ranked = sorted(shown, key=lambda v: (ORDER[applicability(prof, v["sid"])[0]], applicability(prof, v["sid"])[1] or 0))
            for v in ranked:
                k, rank = applicability(prof, v["sid"])
                label = LABEL[k] + (f" #{rank + 1}" if k == "binding" else "")
                link = rl(f"[{v['sid']}]({os.path.relpath(v['page_path'], topic_path.parent).replace(chr(92), '/')})")
                mark = "strictest" if v is best else ""
                pgm = f"⟦p.{v['page']}⟧" if v.get("page") else ""
                out.append(f"| {link} | {label} | {fmt_value(v)} ({v['dir']}) | {pgm} | {mark} |")
            out.append("")
            req = None
            if comp:
                req, why = requirement(prof, shown)
                binding = sorted((v for v in shown if applicability(prof, v["sid"])[0] == "binding"),
                                 key=lambda v: applicability(prof, v["sid"])[1])
                if binding:
                    g = binding[0]
                    line = f"→ Governs here: **{fmt_value(g)}** ({g['sid']}, binding #{applicability(prof, g['sid'])[1] + 1})"
                    if req is not g:
                        line += f"; {why} applies"
                    if best is not g and best is not req and applicability(prof, best["sid"])[0] not in ("binding", "client"):
                        line += f". {best['sid']} ({applicability(prof, best['sid'])[0]}) is stricter at {fmt_value(best)}, not required here"
                    out.append(line + ".")
                elif req is not None:
                    out.append(f"→ No binding value; client requirement applies: **{fmt_value(req)}** ({req['sid']}).")
                else:
                    out.append(f"→ No binding value under this profile. Strictest available: {fmt_value(best)} ({best['sid']}).")
            elif len(shown) > 1:
                out.append("→ Not comparable automatically (different units or directions): judge by hand.")
            for d in dec:
                cmp = ""
                if req is not None and isinstance(d.get("value"), (int, float)) and d.get("unit"):
                    mine = base_value(d["value"], d["unit"])
                    if mine[1] == req["base"][1]:
                        cmp = (" — **weaker than the requirement that applies**" if stricter(req["base"][0], mine[0], req["dir"])
                               else " — equal to the requirement" if mine[0] == req["base"][0]
                               else f" — stricter than the required {fmt_value(req)}")
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
        elif kind == "table" and is_table(blk):
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
            out += [x for _, x in sorted(rows, key=lambda x: x[0])]
        else:
            out += [rl(l) for l in blk]
    notes = []
    if hidden_rows:
        notes.append(f"rows from {', '.join(sorted(hidden_rows))}")
    if hidden_paras:
        notes.append(f"{hidden_paras} paragraph(s) about excluded sources")
    if notes:
        out += ["", f"_Hidden because this profile excludes them: {'; '.join(notes)}._"]
    out += ["", f"_Generated by `edka view` from `{trel}` on {dt.date.today()}. Cite the source pages, not this view._"]
    return "\n".join(out) + "\n"


def refuse_if_broken(w):
    """view and answer-check read structures; refuse to run on a wiki that cannot be loaded or has type errors."""
    bad = [e for e in w.load_errors if e[0] in ("E000", "E001", "E014", "E019", "E021", "E029")]
    if bad:
        code, path, msg = bad[0]
        sys.exit(f"edka: fix loading errors first ({len(bad)}), e.g. {code} {path}: {msg}. Run `edka validate`.")


def find_project(w, pid):
    pj = next((pj for _, pj in w.projects if pj.get("id") == pid), None)
    if not pj:
        sys.exit(f"edka: no project '{pid}' in projects/")
    return pj


def cmd_view(root, a):
    w = Wiki(root, False)
    refuse_if_broken(w)
    tp = w.page(a.topic)
    if tp is None or w.fm(tp).get("type") != "topic":
        sys.exit(f"edka: {a.topic} is not a topic page")
    project = find_project(w, a.project) if a.project else None
    pname = a.profile or (project or {}).get("profile")
    if not pname:
        sys.exit("edka: give --profile or --project")
    out_dir = Path(a.out).resolve().parent if a.out else None
    text = render_view(w, tp, find_profile(w, pname), project, out_dir)
    if a.out:
        out_dir.mkdir(parents=True, exist_ok=True)
        head = f"---\ntype: index\ngenerated_by: edka view\nsource_topic: {w.rel(tp)}\n---\n" if inside(w.root, a.out) else ""
        Path(a.out).write_text(head + text, encoding="utf-8")
        print(f"wrote {a.out}")
    else:
        print(text)
    return 0


def cmd_answer_check(root, answer, profile=None, project_id=None):
    """List every wiki page an answer cites with its source, pages, mode, applicability and verification; fail if
    the answer cites nothing, cites only topics, cites an excluded source, or states a number no cited page
    (or project decision) supports."""
    w = Wiki(root, False)
    refuse_if_broken(w)
    project = find_project(w, project_id) if project_id else None
    if project:
        profile = profile or project.get("profile")
    prof = find_profile(w, profile) if profile else None
    text = read_text(Path(answer))
    linked = []
    for l in MDLINK_RE.findall(text):
        for base in (Path(answer).parent, w.root):
            t = (base / l).resolve()
            if t in w.pages:
                linked.append(t); break
    for l in WIKILINK_RE.findall(text):
        t, _ = w.link_target(w.root / "x.md", l)
        if t:
            linked.append(t)
    linked = list(dict.fromkeys(linked))
    print(f"answer: {answer}  cited wiki pages: {len(linked)}")
    print(f"{'page':58} {'source':16} {'pages':8} {'mode':10} {'applies':11} verification")
    problems, known, sources_cited = [], set(), 0
    for p in linked:
        fm = w.fm(p)
        v = fm.get("verification")
        st = v.get("status") if isinstance(v, dict) else (legacy_status(v) if isinstance(v, str) else None)
        sid = fm.get("source", "")
        mode = fm.get("transcription") or (w.sources.get(sid) or {}).get("transcription", "")
        if fm.get("type") == "topic":
            st = f"{st} (topic: cite the source pages instead)"
        else:
            sources_cited += 1
        app = applicability(prof, sid)[0] if (prof and sid) else "-"
        if app == "excluded":
            problems.append(f"cites {sid}, which profile {profile} excludes")
        if st in (None, "unverified"):
            problems.append(f"cites an unverified page: {w.rel(p)}")
        print(f"{w.rel(p)[:58]:58} {str(sid)[:16]:16} {str(fm.get('source_pages', ''))[:8]:8} {str(mode)[:10]:10} {app:11} {st}")
        known |= numbers_in(w.pages[p]["body"], w.num_re)
    if not linked:
        problems.append("the answer cites no wiki page")
    elif not sources_cited:
        problems.append("the answer cites only topic pages; cite the source pages")
    if project:
        used = []
        for d in project.get("decisions") or []:
            if not isinstance(d, dict):
                continue
            dn = numbers_in(f"{d.get('value', '')} {d.get('unit', '')}\n{d.get('decision', '')}", w.num_re)
            if dn & numbers_in(text, w.num_re):
                used.append(d.get("id"))
            known |= dn
        print(f"\nproject {project.get('id')} (profile {profile}): decisions supporting numbers in the answer:",
              ", ".join(used) if used else "none")
    missing = sorted(numbers_in(text, w.num_re) - known)
    print("\nnumbers with no support on a linked page:", ", ".join(missing) if missing else "none")
    if missing:
        problems.append(f"unsupported numbers: {', '.join(missing)}")
    for pr in problems:
        print("FAIL:", pr)
    print("RESULT:", "FAIL" if problems else "OK")
    return 1 if problems else 0


# =====================================================================================================
# 12. Writers (each changes as little text as possible and checks its own result before saving)
# =====================================================================================================
def registry_path(root):
    cfg, _ = load_yaml_file(Path(root) / "edka.yaml")
    return Path(root) / ((cfg or {}).get("registry", "sources.yaml") if isinstance(cfg, dict) else "sources.yaml")


ITEM_RE = re.compile(r"^([ \t]*)-[ \t]+", re.M)


def registry_blocks(text):
    """[(start, end, id)] for each top-level list item, whatever the indentation or key order."""
    items = list(ITEM_RE.finditer(text))
    if not items:
        return []
    top = min(len(m.group(1)) for m in items)
    starts = [m.start() for m in items if len(m.group(1)) == top]
    out = []
    for i, s in enumerate(starts):
        e = starts[i + 1] if i + 1 < len(starts) else len(text)
        m = re.search(r"(?m)(?:^[ \t]*(?:-[ \t]+)?(?:\{[ \t]*)?|[{,][ \t]*)id:[ \t]*['\"]?([^'\",}\s#]+)", text[s:e])
        out.append((s, e, m.group(1) if m else None))
    return out


def set_registry_field(text, sid, key, value):
    """Set `key: value` in entry `sid`, editing one line; comments and layout elsewhere are kept."""
    bom = text.startswith("﻿")
    body = text[1:] if bom else text
    blk = next(((s, e) for s, e, i in registry_blocks(body) if i == sid), None)
    if blk is None:
        raise KeyError(sid)
    s, e = blk
    block = body[s:e]
    flow = re.match(r"([ \t]*)-[ \t]+\{", block)
    if flow:                                   # flow-style entry: rewrite this one entry, same indentation
        entry = yaml.safe_load(block.strip()[1:].strip())
        entry[key] = value
        line = flow.group(1) + "- " + yaml.safe_dump(entry, default_flow_style=True, sort_keys=False,
                                                     allow_unicode=True, width=10000).strip() + "\n"
        return ("\ufeff" if bom else "") + body[:s] + line + body[e:]
    keyline = re.search(r"(?m)^([ \t]*)(?:-[ \t]+)?(\w+):", block)
    first_indent = None
    for m in re.finditer(r"(?m)^([ \t]+)(\w+):", block):     # indentation of the keys after the first line
        first_indent = m.group(1); break
    if first_indent is None:
        dash = re.match(r"([ \t]*)-[ \t]+", block)
        first_indent = (dash.group(1) if dash else "") + "  "
    existing = re.search(r"(?m)^(" + re.escape(first_indent) + r"|[ \t]*-[ \t]+)" + re.escape(key) + r":[^\n]*$", block)
    if existing:
        old = existing.group(0)
        comment = re.search(r"\s+#.*$", old)
        new_line = old[:existing.end(1) - existing.start(0)] + f"{key}: {value}" + (comment.group(0) if comment else "")
        block = block[:existing.start()] + new_line + block[existing.end():]
    else:
        anchor = re.search(r"(?m)^[ \t]*(?:-[ \t]+)?raw:[^\n]*\n", block) or re.search(r"(?m)^[^\n]*\n", block)
        pos = anchor.end() if anchor else len(block)
        insert = f"{first_indent}{key}: {value}\n"
        if pos == len(block) and not block.endswith("\n"):
            insert = "\n" + insert
        block = block[:pos] + insert + block[pos:]
    body = body[:s] + block + body[e:]
    return ("﻿" if bom else "") + body


def cmd_hash(root, raw_root=None, force=()):
    root = Path(root)
    reg_path = registry_path(root)
    if not reg_path.exists():
        sys.exit(f"edka: no registry at {reg_path}")
    text = read_text(reg_path) if True else ""
    raw_bytes_bom = reg_path.read_bytes().startswith(b"\xef\xbb\xbf")
    reg, err = load_yaml_file(reg_path)
    if err or not isinstance(reg, list):
        sys.exit(f"edka: cannot read {reg_path}: {err or 'not a list'}")
    w = Wiki(root, True, raw_root)
    if raw_bytes_bom:
        text = "﻿" + text
    refused = 0
    for s in reg:
        if not isinstance(s, dict) or not s.get("id"):
            continue
        raw = w.raw_path(s)
        if not raw.is_file():
            print(f"{s['id']}: raw missing ({s.get('raw')})"); continue
        new = sha256(raw)
        old = s.get("sha256")
        if old == new:
            print(f"{s['id']}: unchanged {new[:12]}"); continue
        if old and s["id"] not in force:
            refused += 1
            print(f"{s['id']}: CHANGED, not re-hashed. Re-verify its pages, then: edka hash {root} --force {s['id']}")
            continue
        text = set_registry_field(text, s["id"], "sha256", new)
        print(f"{s['id']}: {'re-hashed (forced)' if old else 'set'} {new[:12]}")
    check, err = None, None
    try:
        check = yaml.safe_load(text.lstrip("﻿"))
    except yaml.YAMLError as e:
        err = str(e)
    if err or not isinstance(check, list):
        sys.exit(f"edka: refusing to write {reg_path}: the edit would not parse ({err})")
    reg_path.write_text(text, encoding="utf-8", newline="\n")
    return 1 if refused else 0


SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def inside(root, path):
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
        return True
    except ValueError:
        return False


def cmd_new_source(root, a):
    root = Path(root)
    if not SLUG_RE.match(a.id):
        sys.exit("edka: --id must be a lower-case slug such as nec-2017")
    if a.pages < 1:
        sys.exit("edka: --pages must be 1 or more")
    if not ((Path(a.raw_root) if a.raw_root else root) / a.raw).is_file() and not a.not_redistributable:
        sys.exit(f"edka: raw file {a.raw} not found; add it first (or use --not-redistributable with --raw-root)")
    reg_path = registry_path(root)
    text = read_text(reg_path) if reg_path.exists() else ""
    reg, err = load_yaml_file(reg_path)
    if err:
        sys.exit(f"edka: cannot read {reg_path}: {err}")
    reg = reg or []
    if any(isinstance(s, dict) and s.get("id") == a.id for s in reg):
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
    items = list(ITEM_RE.finditer(text))
    indent = min((m.group(1) for m in items), key=len) if items else ""
    dumped = yaml.safe_dump([entry], sort_keys=False, allow_unicode=True)
    dumped = "".join(indent + l if l.strip() else l for l in dumped.splitlines(True))
    new_text = text + ("" if not text or text.endswith("\n") else "\n") + dumped
    try:
        check = yaml.safe_load(new_text)
        assert isinstance(check, list) and any(isinstance(s, dict) and s.get("id") == a.id for s in check)
        assert len(check) == len(reg) + 1
    except Exception:
        sys.exit(f"edka: refusing to write {reg_path}: appending would not give a valid registry. Add the entry by hand.")
    reg_path.write_text(new_text, encoding="utf-8", newline="\n")
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
    return 0


def cmd_new_topic(root, a):
    root = Path(root)
    path = root / a.path
    if not inside(root, path) or not str(a.path).endswith(".md"):
        sys.exit("edka: the topic path must be a .md file inside the wiki")
    if path.exists():
        sys.exit(f"edka: {a.path} exists")
    w = Wiki(root, False)
    ids = [x.strip() for x in a.sources.split(",") if x.strip()]
    unknown = [i for i in ids if i not in w.sources]
    if unknown:
        sys.exit(f"edka: unknown source id(s): {', '.join(unknown)}")
    cov = "\n".join(f"  - {{source: {i}, locators: [], depth: not-opened}}   # set depth when you have read it" for i in ids)
    others = [i for i, s in w.sources.items() if i not in ids and s.get("status") == "active"]
    sil = "\n".join(f"  - {{source: {i}, reason: \"TODO: checked? what was read?\", depth: not-opened}}" for i in others)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""---
type: topic
title: {json.dumps(a.title, ensure_ascii=False)}
sources_covered:
{cov}
sources_silent:{chr(10) + sil if sil else " []"}
conflicts: []
derived_from: []
verification: {{status: derived}}
updated: {dt.date.today()}
---
What each source says on this question, side by side. Report the sources only; precedence comes from profiles.
Link every row to its source page; `edka view <topic> --profile <name>` shows precedence.

| Source | What it says | Value | Page |
|---|---|---|---|
""", encoding="utf-8", newline="\n")
    print(f"created {a.path}: {len(ids)} covered (depth not-opened until read), {len(others)} other active sources listed as silent to confirm")
    return 0


# =====================================================================================================
# 13. Command line
# =====================================================================================================
def cmd_explain(code):
    code = code.upper()
    if code not in CODES:
        sys.exit(f"edka: unknown code {code}")
    msg, fix = CODES[code]
    kind = {"E": "error", "W": "warning", "I": "information"}[code[0]]
    promoted = [lvl for lvl, s in LEVEL_PROMOTE.items() if code in s]
    print(f"{code} ({kind}{'; error at level ' + ', '.join(promoted) if promoted else ''})\n  what: {msg}\n  fix:  {fix}")
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):   # Windows consoles default to a legacy code page
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(prog="edka", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"edka {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate"); v.add_argument("root"); v.add_argument("--json"); v.add_argument("--legacy", action="store_true")
    v.add_argument("--strict", action="store_true", help="treat every warning as an error")
    v.add_argument("--max", type=int, default=8); v.add_argument("--raw-root", help="folder holding raw files kept outside the repo")
    s = sub.add_parser("stats"); s.add_argument("root"); s.add_argument("--legacy", action="store_true")
    h = sub.add_parser("hash"); h.add_argument("root"); h.add_argument("--raw-root")
    h.add_argument("--force", nargs="+", default=[], metavar="ID", help="re-hash these changed sources after re-verifying them")
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
    ex = sub.add_parser("explain"); ex.add_argument("code")
    a = ap.parse_args(argv)
    if a.cmd == "explain":
        return cmd_explain(a.code)
    root = Path(a.root)
    if a.cmd == "hash":
        return cmd_hash(root, a.raw_root, set(a.force))
    if a.cmd == "new-source":
        return cmd_new_source(root, a)
    if a.cmd == "new-topic":
        return cmd_new_topic(root, a)
    if a.cmd == "answer-check":
        return cmd_answer_check(root, Path(a.answer), a.profile, a.project)
    if a.cmd == "view":
        return cmd_view(root, a)
    w, r, stats = validate(root, a.legacy, getattr(a, "raw_root", None), getattr(a, "strict", False))
    if a.cmd == "stats":
        print(json.dumps(stats, indent=1, sort_keys=True))
        return 1 if any(c == "E000" for c, _, _ in w.load_errors) else 0
    print_report(w, r, stats, a.max)
    if a.json:
        findings = {k: [{**it, "severity": "error" if r.is_error(k) else ("info" if k.startswith("I") else "warning"),
                         "fix": CODES.get(k, ("", ""))[1]} for it in v] for k, v in r.items.items()}
        Path(a.json).write_text(json.dumps({"version": __version__, "root": str(w.root), "legacy": w.legacy,
                                            "level": w.cfg.get("level"), "stats": stats, "errors": r.errors(),
                                            "warnings": r.warnings(), "findings": findings,
                                            "codes": {k: {"message": m, "fix": f} for k, (m, f) in CODES.items()}},
                                           indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return 1 if r.errors() else 0


if __name__ == "__main__":
    sys.exit(main())
