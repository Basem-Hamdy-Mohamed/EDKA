# Contributing

Thanks for helping. EDKA is small on purpose: one spec, one CLI, plain files.

## License of contributions
By contributing you agree that your code is licensed under Apache-2.0 and your documentation under
CC BY 4.0, the same as the rest of the project.

## Before you open a pull request
```bash
pip install pyyaml
python -m unittest discover -s tests -v
python tools/edka.py validate examples/demo-wiki
python tools/edka.py validate examples/lighting-escape-route --raw-root <your-copy-of-the-pdfs>   # optional
```

## Rules
- **No copyrighted source documents.** Never commit a standard, code or book, or long verbatim
  extracts from one. Example raw files must be public domain, openly licensed or fictional.
- **A new check needs a test.** Add a case to `tests/test_edka.py` that breaks the demo wiki in the way
  your check detects.
- **Spec changes come first.** If a check needs a new field, change `SPEC.md` in the same pull request
  and explain why the field is needed.
- **Keep the validator dependency-free** apart from PyYAML (and `pdftotext` when it is available).

## Good first contributions
- Coverage-map parsing for other table layouts
- A JSON Schema export of the frontmatter contract
- An example from a public-domain regulation, with page images and a verification report
