"""Hardening tests: every case found by the first independent review, plus the writer and CLI fixes.

Each case mutates a small two-source wiki (tests/_cases.py) and states what the validator must report.
"""
import contextlib, io, os, shutil, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "tools"))
import _cases  # noqa: E402
import _cases2  # noqa: E402
import _cases3  # noqa: E402
import edka    # noqa: E402

# case prefix -> codes that must be reported as errors ("E…" or promoted "W…"); "clean" = nothing at all
EXPECT = {
    "00": "clean", "01": {"E015"}, "02": {"E015"}, "03": {"E015"}, "04": {"E031"}, "05": {"E016"},
    "06": {"E016"}, "07": "clean", "08": {"E025"}, "09": {"E002", "E003"}, "10": {"W124"}, "11": {"E001"},
    "12": "clean", "13": {"E019"}, "14": {"E003"}, "15": {"E011"}, "16": {"E027", "W114"}, "17": {"E008"},
    "18": {"E026"}, "19": "clean", "20": {"E018"}, "21": {"W107"}, "22": {"E012"}, "23": {"E024"},
    "24": {"E024"}, "25": {"E028"}, "26": {"E014"}, "27": {"E029"}, "28": {"E030"}, "29": {"E002"},
    "30": {"E031"}, "31": {"E007"}, "32": {"E008"}, "33": {"E014"}, "34": {"W122"}, "35": {"W126", "E027"},
    "36": "clean", "37": {"W120"}, "38": {"W104"}, "39": {"E015"}, "40": {"E000"},
}
WARNING_OK = {"10", "21", "34", "37"}   # cases whose finding is (correctly) a warning, not an error


def quiet(fn, *a, **k):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **k)


class Base(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.base = cls.tmp / "base"
        quiet(_cases.build, cls.base)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def fresh(self):
        root = self.tmp / f"m{id(self)}"
        shutil.rmtree(root, ignore_errors=True)
        shutil.copytree(self.base, root)
        self.addCleanup(shutil.rmtree, root, True)
        return root

    def found(self, root, **kw):
        _, r, _ = edka.validate(root, **kw)
        return r, {k for k, v in r.items.items() if v and not k.startswith("I")}


class TestReviewCases(Base):
    def test_all_cases(self):
        self.assertEqual(len(_cases.CASES), 41)
        for name, fn in _cases.CASES:
            prefix = name[:2]
            with self.subTest(case=name):
                root = self.fresh()
                fn(root)
                r, codes = self.found(root)
                want = EXPECT[prefix]
                if want == "clean":
                    self.assertEqual(codes, set(), f"{name}: expected nothing, got {sorted(codes)}")
                    continue
                self.assertTrue(want <= codes, f"{name}: expected {sorted(want)}, got {sorted(codes)}")
                if prefix not in WARNING_OK:
                    self.assertGreater(r.errors(), 0, f"{name}: should fail the run")


# second review: codes that must appear ("clean" = nothing; "limit" = documented limitation, must not crash)
EXPECT2 = {
    "N01": ("absent", {"E016"}), "N02": ("absent", {"E016"}), "N03a": "clean", "N03b": "clean", "N04": {"E018", "W127"}, "N05": "clean",
    "N06a": {"E027"}, "N06b": {"E027"}, "N06c": {"E027"}, "N07": {"W102"}, "N09": {"E029"}, "N10": {"E028"},
    "N11": {"E015"}, "N12": "limit", "N14": {"E032"}, "N15a": {"E008"}, "N15b": {"E008"}, "N15c": {"W119"},
    "N30": {"W129"}, "N31": {"E033"}, "N32": {"E030"}, "N33": {"E001"}, "N34": {"E031"}, "N35": {"E024"},
    "N36": {"W132"}, "N37": {"E019"}, "N38": {"E019"}, "N39": "strict-clean",
}


class TestSecondReview(Base):
    def test_all_cases(self):
        self.assertEqual(len(_cases2.CASES), len(EXPECT2))
        for name, fn in _cases2.CASES:
            key = name.split()[0]
            want = EXPECT2[key]
            with self.subTest(case=name):
                root = self.fresh()
                fn(root)
                r, codes = self.found(root, strict=(want == "strict-clean"))
                if want in ("clean", "strict-clean"):
                    self.assertEqual(codes, set(), f"{name}: expected nothing, got {sorted(codes)}")
                    self.assertEqual(r.errors(), 0)
                elif want == "limit":
                    pass
                elif isinstance(want, tuple):
                    self.assertFalse(want[1] & codes, f"{name}: must not report {sorted(want[1])}, got {sorted(codes)}")
                else:
                    self.assertTrue(want <= codes, f"{name}: expected {sorted(want)}, got {sorted(codes)}")
                    if not want <= {"W127", "W132", "W102"}:
                        self.assertGreater(r.errors(), 0, f"{name}: should fail the run")


# third review: all run with --strict; ("absent", codes) = must not report them
EXPECT3 = {
    "P00": "clean", "P01": "clean", "P02": "clean", "P03": "clean", "P04": "clean", "P05": "clean", "P06": "clean",
    "P07": "clean", "P08": {"E027"}, "P09": {"E027"}, "P10": {"E032"}, "P11": {"E029"}, "P12": {"E029"}, "P13": "clean",
    "P14": {"E016"}, "P15": "limit", "P16": {"E029"}, "P17": ("absent", {"W129"}), "P18": {"E002"}, "P19": {"E008"},
}


class TestThirdReview(Base):
    def test_all_cases(self):
        import time
        self.assertEqual(len(_cases3.CASES), len(EXPECT3))
        for name, fn in _cases3.CASES:
            want = EXPECT3[name.split()[0]]
            with self.subTest(case=name):
                root = self.fresh()
                quiet(fn, root)
                t0 = time.time()
                r, codes = self.found(root, strict=True)
                self.assertLess(time.time() - t0, 10, f"{name}: too slow")
                errors = {k for k in codes if r.is_error(k)}
                if want == "clean":
                    self.assertEqual(errors, set(), f"{name}: expected no errors under --strict, got {sorted(codes)}")
                elif want == "limit":
                    pass
                elif isinstance(want, tuple):
                    self.assertFalse(want[1] & codes, f"{name}: must not report {sorted(want[1])}, got {sorted(codes)}")
                else:
                    self.assertTrue(want <= codes, f"{name}: expected {sorted(want)}, got {sorted(codes)}")
                    self.assertGreater(r.errors(), 0)


class TestFailClosed(Base):
    def test_missing_root(self):
        r, codes = self.found(self.tmp / "no-such-dir")
        self.assertIn("E000", codes)
        self.assertGreater(r.errors(), 0)

    def test_missing_edka_yaml(self):
        root = self.fresh()
        (root / "edka.yaml").unlink()
        self.assertIn("E000", self.found(root)[1])

    def test_strict_turns_warnings_into_errors(self):
        root = self.fresh()
        _cases.sub(root, _cases.T, "What each source says.", "GDE is softer here.")
        r, _ = self.found(root)
        self.assertEqual(r.errors(), 0)
        r, _ = self.found(root, strict=True)
        self.assertGreater(r.errors(), 0)

    def test_cli_exit_code_on_missing_root(self):
        self.assertEqual(quiet(edka.main, ["validate", str(self.tmp / "nope")]), 1)

    def test_link_case_mismatch(self):
        root = self.fresh()
        if not (root / "SOURCES").exists() and not os.path.exists(str(root / "INDEX.md").lower().replace("index.md", "INDEX.md")):
            pass
        _cases.sub(root, "index.md", "[a](sources/abc-2020/ramps.md)", "[a](sources/ABC-2020/ramps.md)")
        codes = self.found(root)[1]
        if os.path.exists(root / "sources" / "ABC-2020"):      # case-insensitive file system (Windows, macOS)
            self.assertIn("W123", codes)
        else:                                                   # case-sensitive: the link is simply broken
            self.assertIn("E005", codes)


class TestWriters(Base):
    def test_hash_refuses_changed_raw_without_force(self):
        root = self.fresh()
        _cases.sub(root, "raw/abc-2020.txt", "Index.", "Index, revised.")
        before = (root / "sources.yaml").read_text(encoding="utf-8")
        self.assertEqual(quiet(edka.cmd_hash, root), 1)
        self.assertEqual((root / "sources.yaml").read_text(encoding="utf-8"), before)
        quiet(edka.cmd_hash, root, None, {"abc-2020"})
        self.assertNotIn("E007", self.found(root)[1])

    def test_hash_on_indented_registry_with_bom_and_id_not_first(self):
        root = self.fresh()
        reg = root / "sources.yaml"
        text = reg.read_text(encoding="utf-8")
        text = "\n".join(("  " + l) if l.strip() else l for l in text.splitlines()) + "\n"
        text = text.replace("  - id: abc-2020\n    title: Accessible Building Code\n",
                            "  - title: Accessible Building Code   # first key is not id\n    id: abc-2020\n")
        text = "\n".join(l for l in text.splitlines() if "sha256:" not in l) + "\n"
        reg.write_text(text, encoding="utf-8-sig")
        quiet(edka.cmd_hash, root)
        out = reg.read_text(encoding="utf-8-sig")
        self.assertIn("# first key is not id", out)
        self.assertEqual(out.count("sha256:"), 2)
        self.assertNotIn("W106", self.found(root)[1])

    def test_new_source_on_indented_registry(self):
        root = self.fresh()
        reg = root / "sources.yaml"
        reg.write_text("\n".join(("  " + l) if l.strip() else l for l in reg.read_text(encoding="utf-8").splitlines()) + "\n",
                       encoding="utf-8")
        (root / "raw/x.txt").write_text("x", encoding="utf-8")
        quiet(edka.main, ["new-source", str(root), "--id", "x-2020", "--title", "X: the \"big\" one", "--edition", "2020",
                          "--raw", "raw/x.txt", "--pages", "1"])
        import yaml
        data = yaml.safe_load(reg.read_text(encoding="utf-8"))
        self.assertEqual([s["id"] for s in data][-1], "x-2020")

    def test_new_topic_quotes_title_and_stays_inside(self):
        root = self.fresh()
        quiet(edka.main, ["new-topic", str(root), "topics/a/b.md", "--title", 'The "big" one: x', "--sources", "abc-2020"])
        fm = edka.Wiki(root).fm((root / "topics/a/b.md").resolve())
        self.assertEqual(fm["title"], 'The "big" one: x')
        self.assertIn("not-opened", (root / "topics/a/b.md").read_text(encoding="utf-8"))
        with self.assertRaises(SystemExit):
            quiet(edka.main, ["new-topic", str(root), "../escaped.md", "--title", "x", "--sources", "abc-2020"])
        self.assertFalse((root.parent / "escaped.md").exists())

    def test_hash_on_flow_style_registry(self):
        root = self.fresh()
        reg = root / "sources.yaml"
        import yaml
        data = yaml.safe_load(reg.read_text(encoding="utf-8"))
        for s in data:
            s.pop("sha256", None)
        reg.write_text("".join("- " + yaml.safe_dump(s, default_flow_style=True, sort_keys=False, width=10000)
                               for s in data), encoding="utf-8")
        self.assertEqual(quiet(edka.cmd_hash, root), 0)
        self.assertEqual(reg.read_text(encoding="utf-8").count("sha256"), 2)
        self.assertNotIn("W106", self.found(root)[1])

    def test_view_out_into_new_folder(self):
        root = self.fresh()
        out = root / "views" / "deep" / "v.md"
        quiet(edka.main, ["view", str(root), _cases.T, "--project", "p1", "--out", str(out)])
        self.assertTrue(out.exists())

    def test_view_with_repeated_key_does_not_crash(self):
        root = self.fresh()
        _cases.CASES[10][1](root)
        quiet(edka.main, ["view", str(root), _cases.T, "--project", "p1"])


class TestAnswerCheck(Base):
    def check(self, root, text, **kw):
        ans = root / "answer.md"
        ans.write_text(text, encoding="utf-8")
        return quiet(edka.cmd_answer_check, root, ans, kw.get("profile"), kw.get("project"))

    def test_uncited_answer_fails(self):
        self.assertEqual(self.check(self.fresh(), "Ramps 12 m wide, RCD 30 mA."), 1)

    def test_topic_only_citation_fails(self):
        self.assertEqual(self.check(self.fresh(), "Slope 8 % ([t](topics/access/ramps.md))."), 1)

    def test_cited_supported_answer_passes(self):
        self.assertEqual(self.check(self.fresh(), "Slope at most 8 % ([ABC](sources/abc-2020/ramps.md))."), 0)


class TestExplain(unittest.TestCase):
    def test_every_code_explains(self):
        for code in edka.CODES:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                edka.cmd_explain(code)
            self.assertIn("fix:", out.getvalue())


if __name__ == "__main__":
    unittest.main()
