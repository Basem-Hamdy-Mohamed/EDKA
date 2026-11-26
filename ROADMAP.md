# Roadmap

## v0.1: spec + validator (this draft)
- [x] SPEC.md: functional layers, frontmatter contract, profiles, coverage, negative evidence
- [x] `tools/edka.py`: `validate`, `hash`, `stats`, `--legacy`, `--json`
- [x] Fictional demo wiki + 23 fault-injection tests
- [x] Real-source example without source text (escape-route lighting), checked against the PDFs with `--raw-root`
- [x] Number checks (topic ↔ source page ↔ raw PDF text), verbatim check, author ≠ verifier
- [x] Validator run on the private reference wiki (legacy mode)
- [x] License: Apache-2.0 (code) + CC BY 4.0 (docs); LICENSE, LICENSE-docs, NOTICE
- [ ] CODE_OF_CONDUCT.md
- [ ] GitHub Actions running the tests and validating the demo

## v0.2: make it usable by an agent
- [x] `AGENTS.md` template: ingest / verify / synthesise / query workflows that write EDKA fields
- [x] `edka.py new-source` and `new-topic`: scaffold registry entries, coverage maps and topics
- [x] `edka.py answer-check`: given an answer draft, list each cited value with its page and verification status
- [ ] JSON Schema files exported from the spec (for editors and other validators)
- [ ] A migration guide from a plain LLM wiki to EDKA Core

## v0.3: prove it on a public corpus
- [ ] A second example built from **public-domain** regulations (for example US federal regulations),
      with real page images and an independent-verification run
- [ ] A short write-up of the failure modes EDKA caught, with numbers (before/after the validator)

## v1.0
- [ ] Spec frozen at Core, Coverage, Synthesis and Governed levels
- [ ] Validator on PyPI (`pip install edka`)
- [ ] Interop notes: how to run EDKA checks on wikis produced by llm-wiki-compiler or synthadoc

## Not planned
- A database, a server or a UI. EDKA stays plain files and one CLI.
- Folders called GOVERNANCE/, RETRIEVAL/ or VALIDATION/. Those are rules and tools, not folders.
