"""Third-review mutation cases (P00-P19). Used by test_hardening.py."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _cases as B  # noqa: E402
from _cases import w, sub, T, A, G  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn)); return fn
    return deco


EV = "evidence/gde-2021.json"
def ev(r, **kw):
    d = {"source": "gde-2021", "pages_checked": [2], "verifier": "checker-b", "findings": [], "not_checked": ["prose wording"]}
    d.update(kw); w(r, EV, json.dumps(d))

@case("P00 baseline strict")
def _(r): pass
@case("P01 honest prose: 'see Table 4-A and Annex 2-N; supply 230/400 V' on source page + raw")
def _(r):
    sub(r, "raw/gde-2021.txt", "Standby lighting 2 hours.", "Standby lighting 2 hours. See Table 4-A and Annex 2-N. Supply 230/400 V.")
    B.edka.cmd_hash(r, None, {"gde-2021"})
    sub(r, G, "Standby 2 hours.", "Standby 2 hours. See Table 4-A and Annex 2-N. Supply is 230 V single-phase (230/400 V system).")
@case("P02 honest topic prose: 'for residential projects the guide gives...' / 'Designers should follow the manufacturer data'")
def _(r): sub(r, T, "What each source says.", "What each source says. ⟦src:gde-2021⟧ GDE notes that for residential projects ramps are often shorter.")
@case("P03 third active source registered (unrelated catalogue): must every topic list it?")
def _(r):
    w(r, "raw/cat-2022.txt", "=== page 1 ===\nCatalogue of door handles.\n")
    w(r, "sources/cat-2022/coverage.md", "---\ntype: coverage\nsource: cat-2022\n---\n| Pages | Wiki page | Treatment |\n|---|---|---|\n| 1 | — | no-relevant-content: handles |\n")
    p = r / "sources.yaml"; p.write_text(p.read_text(encoding="utf-8") + "- id: cat-2022\n  title: Cat\n  edition: \"2022\"\n  kind: catalogue\n  raw: raw/cat-2022.txt\n  pages: 1\n  transcription: paraphrase\n  folder: sources/cat-2022\n  status: active\n", encoding="utf-8")
    B.edka.cmd_hash(r, None, set())
@case("P04 second table on topic without links (symbols/definitions) + grouped rows (link only on first row)")
def _(r):
    p = r / T; p.write_text(p.read_text(encoding="utf-8") + "\n| Term | Meaning |\n|---|---|\n| slope | rise over run |\n", encoding="utf-8")
@case("P05 evidence: findings ['no discrepancies found']")
def _(r): ev(r, findings=["no discrepancies found"])
@case("P06 evidence: finding status 'closed' / 'corrected'")
def _(r): ev(r, findings=[{"id": 1, "text": "typo", "status": "closed"}])
@case("P07 evidence: not_checked ['prose wording on all pages']")
def _(r): ev(r, not_checked=["prose wording on all pages"])
@case("P08 evidence JSON wrong types: findings: 5, pages_checked: 2, not_checked: 3")
def _(r): ev(r, findings=5, pages_checked=2, not_checked=3)
@case("P09 evidence JSON: reports: [5, 'x'], verifier: 7")
def _(r): w(r, EV, json.dumps({"reports": [5, "x", {"source": "gde-2021", "verifier": 7, "pages_checked": ["a", None, {"x": 1}], "not_checked": None, "findings": {"a": 1}}]}))
@case("P10 calc abuse v2: wrong row + '⟦calc⟧ (rev 2026-11-26)' and '⟦calc⟧ n=1'")
def _(r): sub(r, T, "| max 8 % | 1.2 m | ⟦p.2⟧ |", "| max 80 % | 12 m | ⟦p.2⟧ ⟦calc⟧ rev 2026-11-26 |"); sub(r, A, "RCD 30 mA.", "RCD 300 mA (n=1) ⟦calc⟧.")
@case("P11 history: abuse — active source put in history to hide undeclared conflict")
def _(r):
    p = r / T; t = p.read_text(encoding="utf-8"); a = t.index("conflicts:"); b = t.index("derived_from:")
    p.write_text(t[:a] + "conflicts: []\nhistory: [gde-2021]\n" + t[b:], encoding="utf-8")
    sub(r, T, "  - {source: gde-2021, locators: [\"p2\"], depth: raw}\n", ""); sub(r, "projects/p1.yaml", "    conflict: R-1\n", "")
@case("P12 source_pages '1-30000000' (typo) — time")
def _(r): sub(r, G, 'source_pages: "2"', 'source_pages: "1-30000000"')
@case("P13 honest elision mid-sentence keeping meaning: 'The slope of a ramp shall not exceed 8 %. … not less than 1.2 m.'")
def _(r): sub(r, A, "The clear width of a ramp shall be not less than 1.2 m.", "… shall be not less than 1.2 m.")
@case("P14 negation dropped across abbreviation boundary: 'shall, e.g. in ramps, not exceed' style -> quote 'shall … exceed 8 %' where raw has 'shall (see 3.2.) not exceed'")
def _(r):
    sub(r, "raw/abc-2020.txt", "The slope of a ramp shall not exceed 8 %.", "The slope of a ramp shall (cf. cl. 3.2) not exceed 8 %.")
    B.edka.cmd_hash(r, None, {"abc-2020"})
    sub(r, A, "The slope of a ramp shall not exceed 8 %.", "The slope of a ramp shall … exceed 8 %.")
@case("P15 E018 evasion v2: column 'Governing?' / 'Status in KSA' ; prose 'This is what you must design to in Homeland: 8 %.'")
def _(r):
    sub(r, T, "| Source | Slope | Width | Page |", "| Source | Slope | Status in Homeland | Page |"); sub(r, T, "| 1.2 m |", "| law |"); sub(r, T, "| 1.5 m |", "| optional |")
@case("P16 locators given as a string, depth missing, extra unknown keys")
def _(r): sub(r, T, '{source: abc-2020, locators: ["3.1"], depth: raw}', '{source: abc-2020, locators: "3.1", note: hello}')
@case("P17 topic with only one covered source and hours-vs-minutes same value (60 minutes vs 1 h) — no W129 expected")
def _(r): sub(r, G, "value: 2, unit: \"hours\"", "value: 1, unit: \"h\""); sub(r, G, "Standby 2 hours.", "Standby 1 h. Also 2 hours elsewhere.")
@case("P18 frontmatter key typo: 'sources_silnt', 'verfication' on topic")
def _(r): sub(r, T, "sources_silent: []", "sources_silnt: []")
@case("P19 coverage row '1-3' range typo '1-99999999'")
def _(r): sub(r, "sources/gde-2021/coverage.md", "| 1 | — | not-ingested: cover |", "| 1-20000000 | — | not-ingested: cover |")

