"""Each test breaks the demo wiki in one way and checks that the validator reports the right code.

Run:  python -m unittest discover -s tests -v
"""
import re, shutil, sys, tempfile, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import edka  # noqa: E402

DEMO = ROOT / "examples" / "demo-wiki"
TOPIC = "topics/distribution/voltage-drop.md"
DEC = "sources/dec-2024/ch4-voltage-drop.md"


class DemoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.w = self.tmp / "w"
        shutil.copytree(DEMO, self.w)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def edit(self, rel, old, new, count=1):
        p = self.w / rel
        t = p.read_text(encoding="utf-8")
        self.assertIn(old, t, f"fixture text not found in {rel}")
        p.write_text(t.replace(old, new, count), encoding="utf-8", newline="\n")

    def codes(self):
        _, r, _ = edka.validate(self.w, legacy=False)
        return {k: v for k, v in r.items.items() if v}

    def assertCode(self, code):
        c = self.codes()
        self.assertIn(code, c, f"expected {code}, got {sorted(c)}")


class TestDemoIsClean(DemoCase):
    def test_clean(self):
        self.assertEqual(self.codes(), {})


class TestIntegrity(DemoCase):
    def test_raw_changed(self):
        self.edit("raw/dec-2024.md", "shall not exceed 4 %", "shall not exceed 3 %")
        self.assertCode("E007")

    def test_raw_missing(self):
        (self.w / "raw/usc-2022.md").unlink()
        self.assertCode("E006")


class TestCoverage(DemoCase):
    def test_gap(self):
        self.edit("sources/dec-2024/coverage.md", "| 5 | — | no-relevant-content: mechanical clauses only |\n", "")
        self.assertCode("E008")

    def test_overlap(self):
        self.edit("sources/dec-2024/coverage.md", "| 5 |", "| 3-5 |")
        self.assertCode("E008")

    def test_unknown_treatment(self):
        self.edit("sources/dec-2024/coverage.md", "no-relevant-content: mechanical", "skipped: mechanical")
        self.assertCode("W111")


class TestNegativeEvidence(DemoCase):
    def test_weak_depth(self):
        self.edit(TOPIC, "tariffs)\", depth: raw}", "tariffs)\", depth: index}")
        self.assertCode("W105")

    def test_missing_reason(self):
        self.edit(TOPIC, re.search(r"reason: \"[^\"]+\", ", (self.w / TOPIC).read_text(encoding="utf-8")).group(0), "")
        self.assertCode("E009")


class TestProfiles(DemoCase):
    def test_excluded_source_in_topic(self):
        (self.w / "edka.yaml").write_text((self.w / "edka.yaml").read_text(encoding="utf-8")
                                          + "excluded_from_topics: [foreign-code-x]\n", encoding="utf-8")
        self.edit("sources.yaml", "- id: dec-2018", "- id: foreign-code-x\n  title: Foreign code\n  edition: \"2020\"\n"
                  "  kind: normative\n  raw: raw/dec-2018.md\n  pages: 4\n  transcription: paraphrase\n"
                  "  folder: sources/dec-2018\n  status: active\n- id: dec-2018")
        self.edit(TOPIC, "sources_covered:\n", "sources_covered:\n  - {source: foreign-code-x, locators: [\"1\"], depth: wiki}\n")
        self.assertCode("E012")

    def test_resolved_by_profile_without_binding(self):
        self.edit(TOPIC, "between: [dec-2024, dgd-2019]", "between: [dgd-2019, dec-2018]")
        self.assertCode("E011")

    def test_withdrawn_source(self):
        self.edit("sources.yaml", "folder: sources/dgd-2019\n  status: active", "folder: sources/dgd-2019\n  status: withdrawn")
        self.assertCode("W107")


class TestVerification(DemoCase):
    def test_independent_without_verifier(self):
        self.edit(DEC, "  by: verifier-agent-2\n", "")
        self.assertCode("E013")

    def test_bad_status(self):
        self.edit(DEC, "status: independent", "status: looks-fine")
        self.assertCode("E004")


class TestEvidence(DemoCase):
    def test_topic_number_not_in_sources(self):
        self.edit(TOPIC, "Total ≤ 4 % (\"shall\")", "Total ≤ 3.5 % (\"shall\")")
        self.assertCode("E015")

    def test_calc_line_is_allowed(self):
        self.edit(TOPIC, "USC 2022 is silent", "Example: 2 % + 1.5 % = 3.5 % ⟦calc⟧\n\nUSC 2022 is silent")
        self.assertNotIn("E015", self.codes())

    def test_verbatim_quote_altered(self):
        self.edit(DEC, "shall not exceed 4 %.", "shall not exceed 4 % in any case.")
        self.assertCode("E016")

    def test_verbatim_quote_from_other_page(self):
        # the quote exists in the raw file, but on page 5, outside source_pages 3-4
        self.edit(DEC, "> 4.3 Motor starting is not covered by 4.2.",
                  "> 7 Mechanical clauses. Enclosure fixings, gland plates and paint finish.")
        self.assertCode("E016")

    def test_number_not_in_raw(self):
        self.edit("sources/dgd-2019/s3-cable-sizing.md", "**2 %** on feeders", "**2.5 %** on feeders")
        self.assertCode("E031")          # text raw: an error (a PDF scan would give the W116 warning)

    def test_self_verification(self):
        self.edit(DEC, "author: author-agent-1", "author: verifier-agent-2")
        self.assertCode("E017")

    def test_not_redistributable_raw(self):
        (self.w / "raw/usc-2022.md").unlink()
        self.edit("sources.yaml", "folder: sources/usc-2022\n", "folder: sources/usc-2022\n  redistributable: false\n")
        c = self.codes()
        self.assertNotIn("E006", c)
        self.assertIn("I001", c)


class TestSynthesis(DemoCase):
    def test_stale_topic(self):
        self.edit(DEC, "updated: 2026-11-26", "updated: 2026-12-15")
        self.assertCode("W101")

    def test_marker_outside_range(self):
        self.edit(DEC, "⟦p.4⟧", "⟦p.9⟧")
        self.assertCode("W102")

    def test_broken_link(self):
        self.edit(TOPIC, "../../sources/dgd-2019/s3-cable-sizing.md", "../../sources/dgd-2019/missing.md")
        self.assertCode("E005")


class TestNeutralTopics(DemoCase):
    def test_binding_column_rejected(self):
        self.edit(TOPIC, "| Source | What it says | Page |", "| Source | Binding here? | What it says | Page |")
        self.assertCode("E018")

    def test_profile_answer_rejected(self):
        self.edit(TOPIC, "What each source says", "Answer under profile demo-land-building: 4 %. What each source says")
        self.assertCode("E018")

    def test_profile_unknown_source(self):
        self.edit("profiles/demo-land-building.yaml", "reference: [dgd-2019]", "reference: [dgd-2019, nope-1999]")
        self.assertCode("E019")

    def test_no_binding_side_under_second_profile(self):
        (self.w / "profiles/guide-only.yaml").write_text(
            "name: guide-only\nbinding: []\nreference: [dec-2024, dgd-2019]\nexcluded: []\n", encoding="utf-8")
        self.assertCode("W118")


LIGHT = ROOT / "examples" / "lighting-escape-route"
LTOPIC = "topics/lighting/escape-route-illuminance-and-duration.md"


class TestProfileViews(unittest.TestCase):
    def view(self, profile):
        w = edka.Wiki(LIGHT, False)
        return edka.render_view(w, (LIGHT / LTOPIC).resolve(), edka.find_profile(w, profile))

    def test_saudi(self):
        v = self.view("saudi-new-building")
        self.assertIn("**sbc801-2018** (binding #1", v)
        self.assertIn("sbc401-2024 is binding here but **silent**", v)
        self.assertIn("**EL-1** (sbc801-2018 vs nfpa101-2018): sbc801-2018 governs", v)

    def test_us(self):
        v = self.view("us-ahj-nfpa101-2018")
        self.assertIn("**nfpa101-2018** (binding #1", v)
        self.assertNotIn("[SBC 801", v)                      # excluded rows hidden
        self.assertIn("EL-1** (sbc801-2018 vs nfpa101-2018): not applicable here", v)
        self.assertIn("nfpa101-2018 governs", v)            # EL-4 duration

    def test_units(self):
        self.assertEqual(edka.numbers_in("1000 kVA, 50 Hz, 40 °C, 65 dB(A), 22 kW"),
                         {"1000 kVA", "50 Hz", "40 °C", "65 dB(A)", "22 kW"})


class TestProjects(DemoCase):
    PJ = "projects/pump-station-07.yaml"

    def test_project_decision_missing(self):
        (self.w / self.PJ).unlink()
        self.assertCode("E020")

    def test_decision_unknown_conflict(self):
        self.edit(self.PJ, "conflict: VD-2", "conflict: VD-9")
        self.assertCode("E021")

    def test_unknown_profile(self):
        self.edit(self.PJ, "profile: demo-land-building", "profile: nowhere")
        self.assertCode("E021")

    def test_decision_without_basis(self):
        self.edit(self.PJ, "    basis: \"Design basis report rev B, section 5.3 (demo)\"\n", "")
        self.assertCode("E021")

    def test_row_without_source_link(self):
        self.edit(TOPIC, "| [DEC 2018](../../sources/dec-2018/ch4-voltage-drop.md) |", "| DEC 2018 |")
        self.assertCode("W119")

    def test_untagged_paragraph(self):
        self.edit(TOPIC, "⟦src:usc-2022,dgd-2019⟧ ", "")
        self.assertCode("W120")


class TestProjectViews(unittest.TestCase):
    def test_hotel_decision_overrides_profile(self):
        w = edka.Wiki(LIGHT, False)
        pj = next(p for _, p in w.projects if p["id"] == "hotel-demo")
        v = edka.render_view(w, LIGHT / LTOPIC, edka.find_profile(w, pj["profile"]), pj)
        self.assertIn("**EL-4**", v)
        self.assertIn("**project decision D-01**: 3 hours", v)
        self.assertIn("## Project decisions on this topic", v)

    def test_us_view_hides_tagged_paragraphs(self):
        w = edka.Wiki(LIGHT, False)
        v = edka.render_view(w, LIGHT / LTOPIC, edka.find_profile(w, "us-ahj-nfpa101-2018"))
        self.assertNotIn("so SBC 801 and NFPA 101 agree", v)
        self.assertIn("2 paragraph(s) about excluded sources", v)
        self.assertNotIn("⟦src:", v)

    def test_relink_for_other_folder(self):
        line = "[x](../../sources/a/b.md)"
        out = edka.relink(line, LIGHT / "topics/lighting", LIGHT)
        self.assertEqual(out, "[x](sources/a/b.md)")


class TestValues(DemoCase):
    def test_value_not_in_body(self):
        self.edit(DEC, "{key: vd-total, value: 4,", "{key: vd-total, value: 3.5,")
        self.assertCode("E023")

    def test_bad_direction(self):
        self.edit(DEC, "dir: max, page: 3", "dir: upper, page: 3")
        self.assertCode("E022")

    def test_mixed_units(self):
        self.edit("sources/dec-2018/ch4-voltage-drop.md", "{key: vd-total, value: 5, unit: \"%\"", "{key: vd-total, value: 5, unit: \"V\"")
        self.edit("sources/dec-2018/ch4-voltage-drop.md", "shall not exceed 5 %.", "shall not exceed 5 % (5 V).")
        self.assertCode("W121")

    def test_decision_weaker_than_code(self):
        pj = self.w / "projects/pump-station-07.yaml"
        pj.write_text(pj.read_text(encoding="utf-8") + """  - id: D-02
    topic: topics/distribution/voltage-drop.md
    key: vd-total
    value: 5
    unit: "%"
    decision: "5 % total"
    basis: "test"
    date: 2026-11-26
""", encoding="utf-8")
        self.assertCode("E024")

    def test_decision_stricter_is_fine(self):
        pj = self.w / "projects/pump-station-07.yaml"
        pj.write_text(pj.read_text(encoding="utf-8") + """  - id: D-02
    topic: topics/distribution/voltage-drop.md
    key: vd-total
    value: 3
    unit: "%"
    decision: "3 % total"
    basis: "test"
    date: 2026-11-26
""", encoding="utf-8")
        self.assertNotIn("E024", self.codes())


class TestValueViews(unittest.TestCase):
    def render(self, **kw):
        w = edka.Wiki(LIGHT, False)
        if "project" in kw:
            pj = next(p for _, p in w.projects if p["id"] == kw["project"])
            return edka.render_view(w, LIGHT / LTOPIC, edka.find_profile(w, pj["profile"]), pj)
        return edka.render_view(w, LIGHT / LTOPIC, edka.find_profile(w, kw["profile"]))

    def test_saudi_governing_and_stricter_reference(self):
        v = self.render(profile="saudi-new-building")
        self.assertIn("→ Governs here: **90 minutes** (sbc801-2018, binding #1). sll-lg12-2015 (reference) is stricter at 3 hours", v)
        self.assertIn("→ Governs here: **1 lux** (sbc801-2018, binding #1). nfpa101-2018 (reference) is stricter at 1.1 lux", v)

    def test_us_governing(self):
        v = self.render(profile="us-ahj-nfpa101-2018")
        self.assertIn("→ Governs here: **1.5 hours** (nfpa101-2018, binding #1)", v)
        self.assertNotIn("[sbc801-2018]", v)

    def test_project_decision_compared(self):
        v = self.render(project="hotel-demo")
        self.assertIn("**D-01**: 3 h — stricter than the required 90 minutes", v)

    def test_time_units_compare(self):
        self.assertTrue(edka.stricter(edka.base_value(3, "h")[0], edka.base_value(90, "minutes")[0], "min"))
        self.assertEqual(edka.base_value(1.5, "hours"), edka.base_value(90, "min"))


class TestCommandsKeepFiles(DemoCase):
    def reg(self):
        return (self.w / "sources.yaml").read_text(encoding="utf-8")

    def add_comments(self):
        self.edit("sources.yaml", "- id: dec-2024\n", "# Registry of demo sources (kept by hand)\n- id: dec-2024   # current edition\n")
        self.edit("sources.yaml", "  raw: raw/dgd-2019.md\n", "  raw: raw/dgd-2019.md   # copy from the publisher site\n")

    def test_hash_keeps_comments(self):
        self.add_comments()
        self.edit("raw/dgd-2019.md", "Index.", "Index (revised).")   # force a new hash
        before = self.reg()
        self.assertEqual(edka.cmd_hash(self.w), 1)                  # a changed raw file is not re-hashed silently
        self.assertEqual(self.reg(), before)
        self.assertIn("E007", self.codes())
        edka.cmd_hash(self.w, force={"dgd-2019"})
        after = self.reg()
        for c in ("# Registry of demo sources", "# current edition", "# copy from the publisher site"):
            self.assertIn(c, after)
        self.assertNotEqual(before, after)
        self.assertEqual(self.codes(), {})                          # the new hash matches the file

    def test_hash_adds_missing_line(self):
        line = [l for l in self.reg().splitlines() if l.startswith("  sha256:")][1]
        self.edit("sources.yaml", line + "\n", "")
        edka.cmd_hash(self.w)
        self.assertEqual(self.codes(), {})

    def test_new_source_appends_only(self):
        self.add_comments()
        before = self.reg()
        edka.main(["new-source", str(self.w), "--id", "x-2020", "--title", "X", "--edition", "2020",
                   "--raw", "raw/x.md", "--pages", "2"])
        after = self.reg()
        self.assertTrue(after.startswith(before))
        self.assertIn("- id: x-2020", after)


class TestAnswerCheckProject(unittest.TestCase):
    TEXT = "Duration 3 h for the hotel ([SBC 801](sources/sbc801-2018/1008-egress-illumination.md))."

    def run_check(self, text, profile=None, project=None):
        import io, contextlib
        d = Path(tempfile.mkdtemp())
        ans = d / "a.md"
        ans.write_text(text, encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = edka.cmd_answer_check(LIGHT, ans, profile, project)
        shutil.rmtree(d, ignore_errors=True)
        return rc, buf.getvalue()

    def test_without_project_number_unsupported(self):
        rc, out = self.run_check(self.TEXT, profile="saudi-new-building")
        self.assertEqual(rc, 1)
        self.assertIn("3 h", out.split("no support on a linked page:")[1])

    def test_with_project_decision_supports_number(self):
        rc, out = self.run_check(self.TEXT, project="hotel-demo")
        self.assertEqual(rc, 0)
        self.assertIn("decisions supporting numbers in the answer: D-01", out)


class TestDocstring(unittest.TestCase):
    def test_docstring_lists_writers(self):
        doc = edka.__doc__
        self.assertIn("Read-only", doc)
        for cmd in ("hash", "new-source", "new-topic"):
            self.assertIn(cmd, doc.split("Write files")[1])


if __name__ == "__main__":
    unittest.main()
