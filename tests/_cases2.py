"""Second-review mutation cases (N01-N39). Used by test_hardening.py."""
import contextlib, io, json, os, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _cases as B  # noqa: E402
from _cases import w, sub, T, A, G, edka  # noqa: E402

CASES = []


def case(name):
    def deco(fn):
        CASES.append((name, fn)); return fn
    return deco


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


LONG = " ".join(f"Filler sentence number {i} about ramps and landings." for i in range(30))

def raw_extra(r, text):
    sub(r, "raw/abc-2020.txt", "3.2 Protection.", text + "\n3.2 Protection.")
    quiet(edka.cmd_hash, r, None, {"abc-2020"})

@case("N01 honest elision whose cut text contains 'not' (false E016?)")
def _(r): sub(r, A, "> 3.1 Ramps. The slope of a ramp shall not exceed 8 %. The clear width of a ramp shall be not less than 1.2 m.",
              "> 3.1 Ramps. The slope of a ramp shall not exceed 8 %. … Socket circuits shall be protected by a residual current device rated not more than 30 mA.")
@case("N02 honest elision longer than 600 chars (false 'out of order'?)")
def _(r):
    raw_extra(r, LONG + " End of ramps.")
    sub(r, A, "The clear width of a ramp shall be not less than 1.2 m.", "… End of ramps.")
@case("N03a neutral prose quoting a scope rule: 'Clause 3.1 does not apply to kerb ramps' (false E018?)")
def _(r): sub(r, T, "What each source says.", "What each source says. Clause 3.1 does not apply to kerb ramps.")
@case("N03b neutral table header 'Applies to' / 'Applicable clause' (false E018?)")
def _(r): sub(r, T, "| Source | Slope | Width | Page |", "| Source | Slope | Applicable clause | Page |")
@case("N04 E018 evasion: 'In Homeland use the ABC value and ignore GDE' + column 'Use?'")
def _(r):
    sub(r, T, "What each source says.", "In Homeland, designers must use the code value and ignore the guide.")
    sub(r, T, "| Source | Slope | Width | Page |", "| Source | Slope | Use? | Page |"); sub(r, T, "| 1.2 m |", "| YES |"); sub(r, T, "| 1.5 m |", "| no |")
IND = "{status: independent, author: %s, by: %s, date: 2026-11-26, ref: %s}"
OLD = "{status: author-checked, author: me, date: 2026-11-26}"
@case("N05 author agent-1, verifier agent-2 (false E017?)")
def _(r):
    w(r, "evidence/r.json", json.dumps({"source": "abc-2020", "pages_checked": [2], "verifier": "agent-2", "not_checked": []}))
    sub(r, A, OLD, IND % ("agent-1", "agent-2", "evidence/r.json"))
@case("N06a independent with ref: sources.yaml (any file naming the source)")
def _(r): sub(r, A, OLD, IND % ("alice", "bob", "sources.yaml"))
@case("N06b independent with ref JSON = {\"not_checked\": []} only")
def _(r):
    w(r, "evidence/r.json", '{"not_checked": []}')
    sub(r, A, OLD, IND % ("alice", "bob", "evidence/r.json"))
@case("N06c independent; report not_checked lists 'everything' ")
def _(r):
    w(r, "evidence/r.json", json.dumps({"source": "abc-2020", "pages_checked": [2], "verifier": "bob", "not_checked": ["all tables", "all numbers"], "findings": ["8 % is wrong, should be 6 %"]}))
    sub(r, A, OLD, IND % ("alice", "bob", "evidence/r.json"))
@case("N07 values page: '2-3' (non-integer page)")
def _(r): sub(r, A, "dir: max, page: 2, locator", "dir: max, page: \"2-3\", locator")
@case("N09 edka.yaml ignore: ['sources/*/*.md', 'topics/*/*.md'] hides everything")
def _(r):
    w(r, "edka.yaml", "level: governed\nignore: ['sources/*/*.md', 'topics/*/*.md']\n")
    sub(r, T, "max 8 %", "max 99 %")
@case("N10 hollow governed wiki: all pages unverified, coverage all pending")
def _(r):
    sub(r, A, OLD, "{status: unverified}")
    sub(r, G, "{status: independent, author: writer-a, by: checker-b, date: 2026-11-26, ref: evidence/gde-2021.json}", "{status: unverified}")
    for c in ("sources/abc-2020/coverage.md", "sources/gde-2021/coverage.md"):
        p = r / c; t = p.read_text(encoding="utf-8").split("| Pages")[0]; n = 3 if "abc" in c else 2
        p.write_text(t + f"| Pages | Wiki page | Treatment |\n|---|---|---|\n| 1-{n} | — | pending |\n", encoding="utf-8")
@case("N11 unit confusion: topic says 1.2 m/s and 8 %/m ; '8 per cent' unchecked")
def _(r): sub(r, T, "| max 8 % | 1.2 m |", "| max 8 %/m | 1.2 m/s |")
@case("N12 values swapped inside one source's row (min/max of same page): 60 minutes shown as ramp width")
def _(r): sub(r, T, "| max 8 % | 1.2 m |", "| max 30 mA | 60 minutes |")
@case("N14 calc-mark abuse: wrong number + ⟦calc⟧ on the row and on the source page")
def _(r): sub(r, T, "| max 8 % | 1.2 m | ⟦p.2⟧ |", "| max 80 % | 12 m | ⟦p.2⟧ <!-- ⟦calc⟧ --> |"); sub(r, A, "RCD 30 mA.", "RCD 300 mA. <!-- ⟦calc⟧ -->")
@case("N15a coverage map with no table at all")
def _(r): p = r / "sources/abc-2020/coverage.md"; p.write_text(p.read_text(encoding="utf-8").split("| Pages")[0] + "All pages read, trust me.\n", encoding="utf-8")
@case("N15b coverage table header 'PDF pp.' instead of 'Pages', with a gap")
def _(r): sub(r, "sources/abc-2020/coverage.md", "| Pages |", "| PDF pp. |"); sub(r, "sources/abc-2020/coverage.md", "| 3 | — | not-ingested: index |\n", "")
@case("N15c topic table without outer pipes, wrong value, no link")
def _(r):
    p = r / T; t = p.read_text(encoding="utf-8").split("| Source |")[0]
    p.write_text(t + "Source | Slope\n---|---\nABC | max 5 %\nGDE | max 8 %\n\n[a](../../sources/abc-2020/ramps.md) [g](../../sources/gde-2021/ramps.md)\n", encoding="utf-8")
@case("N30 two sources, same key, different values, conflicts: [] (undeclared conflict)")
def _(r):
    p = r / T; t = p.read_text(encoding="utf-8")
    a = t.index("conflicts:"); b = t.index("derived_from:")
    p.write_text(t[:a] + "conflicts: []\n" + t[b:], encoding="utf-8"); sub(r, "projects/p1.yaml", "    conflict: R-1\n", "")
@case("N31 registered active source neither covered nor silent, but its row is on the page")
def _(r): sub(r, T, "  - {source: gde-2021, locators: [\"p2\"], depth: raw}\n", "")
@case("N32 source declared silent, yet a row reports its value")
def _(r): sub(r, T, "  - {source: gde-2021, locators: [\"p2\"], depth: raw}\n", ""); sub(r, T, "sources_silent: []", "sources_silent:\n  - {source: gde-2021, reason: \"says nothing on ramps\", depth: raw}")
@case("N33 page without type (plain note dropped in by a user)")
def _(r): w(r, "notes/todo.md", "# todo\n- ask client\n")
@case("N34 source page: body value unit-less & hyphenated ('90-minute', 'factor 0.8', '8 per cent') wrong vs raw")
def _(r): sub(r, A, "Standby lighting 60 minutes.", "Standby lighting 90-minute rated; ramp 12 per cent; factor 0.8.")
@case("N35 decision value below code but unit differs in spelling (percent vs %); and decision with no key (free text '20 %')")
def _(r): sub(r, "projects/p1.yaml", 'value: 6\n    unit: "%"', 'value: 20\n    unit: percent')
@case("N36 decision without key: text says 20 % ramps (below code), no check possible")
def _(r): sub(r, "projects/p1.yaml", "    key: ramp-slope\n    value: 6\n    unit: \"%\"\n", ""); sub(r, "projects/p1.yaml", "6 % ramps", "20 % ramps")
@case("N37 two profiles with the same name; project picks 'home'")
def _(r): w(r, "profiles/home2.yaml", "name: home\nbinding: [gde-2021]\nreference: [abc-2020]\n")
@case("N38 superseded source is binding in a profile")
def _(r): sub(r, "sources.yaml", "folder: sources/abc-2020\n  status: active", "folder: sources/abc-2020\n  status: withdrawn")
@case("N39 --strict on clean baseline (should stay 0)")
def _(r): pass

