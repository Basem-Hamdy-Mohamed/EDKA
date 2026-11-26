"""Type fuzz: put a wrong-typed value at every YAML path of a small wiki and run validate and view.

    python tests/fuzz_types.py          # full run (a few minutes); prints every crash site
    EDKA_FUZZ_SAMPLE=200 python ...     # random sample (used by the unit tests)

Not part of the unit tests' default run because of its length; test_hardening runs a sample.
"""
import contextlib, copy, io, os, random, re, shutil, sys, tempfile, traceback
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE)); sys.path.insert(0, str(HERE.parent / "tools"))
import _cases  # noqa: E402
import edka    # noqa: E402

BAD = [None, 5, "x", [], {}, [1], {"a": 1}, True, "2026-13-01", [None], [[1]], 1.5, "", ["x", {"source": ["a"]}]]
FILES = ["edka.yaml", "sources.yaml", "profiles/home.yaml", "projects/p1.yaml", _cases.T, _cases.A,
         "sources/abc-2020/coverage.md"]


def walk(o, path=()):
    yield path
    if isinstance(o, dict):
        for k, v in o.items():
            yield from walk(v, path + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from walk(v, path + (i,))


def setp(o, path, val):
    if not path:
        return val
    o = copy.deepcopy(o); c = o
    for k in path[:-1]:
        c = c[k]
    c[path[-1]] = val
    return o


def mutations(base):
    for f in FILES:
        txt = (base / f).read_text(encoding="utf-8")
        if f.endswith(".md"):
            m = re.match(r"\A---\n(.*?)\n---\n", txt, re.S)
            data, rest = yaml.safe_load(m.group(1)), txt[m.end():]
        else:
            data, rest = yaml.safe_load(txt), None
        for path in walk(data):
            for bad in BAD:
                yield f, path, bad, data, rest


def run(sample=None, seed=7):
    tmp = Path(tempfile.mkdtemp())
    base = tmp / "base"
    with contextlib.redirect_stdout(io.StringIO()):
        _cases.build(base)
    muts = list(mutations(base))
    if sample:
        random.Random(seed).shuffle(muts)
        muts = muts[:sample]
    crashes = {}
    root = tmp / "m"
    for f, path, bad, data, rest in muts:
        shutil.rmtree(root, ignore_errors=True)
        shutil.copytree(base, root)
        dumped = yaml.safe_dump(setp(data, path, bad), sort_keys=False, allow_unicode=True)
        (root / f).write_text(("---\n" + dumped + "---\n" + rest) if rest is not None else dumped, encoding="utf-8")
        for cmd in (["validate", str(root)], ["view", str(root), _cases.T, "--project", "p1"],
                    ["view", str(root), _cases.T, "--profile", "home"],
                    ["answer-check", str(root), str(root / "index.md"), "--project", "p1"]):
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    edka.main(cmd)
            except SystemExit:
                pass
            except Exception as e:  # noqa: BLE001
                tb = traceback.extract_tb(e.__traceback__)[-1]
                crashes.setdefault((cmd[0], tb.lineno, type(e).__name__), []).append((f, path, repr(bad)))
    shutil.rmtree(tmp, ignore_errors=True)
    return len(muts), crashes


if __name__ == "__main__":
    n, crashes = run(int(os.environ["EDKA_FUZZ_SAMPLE"]) if os.environ.get("EDKA_FUZZ_SAMPLE") else None)
    print("mutations", n, "crash sites", len(crashes))
    for k, v in sorted(crashes.items()):
        print(k, "x", len(v), "e.g.", v[0])
    sys.exit(1 if crashes else 0)
