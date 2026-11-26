# Roadmap

## v0.2 (current)
- [x] SPEC: layers, frontmatter contract, profiles, projects, structured values, conformance levels
- [x] `edka` CLI: validate (`--strict`, `--legacy`, `--json` with fixes), view, answer-check, explain,
      hash (`--force`), new-source, new-topic
- [x] Fails closed; every finding has a code, a severity and a fix
- [x] 71 tests, including 69 mutation cases from two independent reviews, and a type fuzz in CI
- [x] Fictional demo wiki and a real-standards example without source text
- [x] License (Apache-2.0 + CC BY 4.0), Code of Conduct, CI

## v0.3
- [ ] An example built from **public-domain** regulations, with the PDFs included, so anyone can run
      every check (including verbatim and raw-number checks)
- [ ] JSON Schema files exported from the spec
- [ ] Migration guide from a plain LLM wiki to EDKA Core
- [ ] Split `tools/edka.py` into a package along the same layers

## v1.0
- [ ] Spec frozen; validator on PyPI (`pip install edka`)
- [ ] Interop notes for wikis produced by other LLM-wiki tools

## Not planned
- A database, a server or a UI. EDKA stays plain files and one CLI.
