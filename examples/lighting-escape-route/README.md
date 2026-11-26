# Example: escape-route lighting (real sources, no source text)

This example comes from a real, private wiki built from purchased standards. It shows EDKA on a
question that engineers actually face. **The standards themselves are copyrighted, so this folder holds
no source text and no PDFs.** It holds:

- a **registry** with each document's edition, physical page count and SHA-256, so the owner of a
  licensed copy can check that it is the same file (`--raw-root`);
- **paraphrased source pages** that keep only clause numbers, physical page numbers and the numeric
  values, which are facts;
- one **neutral topic page**, two **profiles** (a new building in Saudi Arabia; a US building where the
  authority has adopted NFPA 101-2018) and one illustrative **project** with two recorded decisions.

```bash
python tools/edka.py validate examples/lighting-escape-route
# with your own copies of the PDFs, laid out as in sources.yaml:
python tools/edka.py validate examples/lighting-escape-route --raw-root /path/to/your/raw
```

With the PDFs present, the validator checks the hashes and that every number on each source page appears
in the PDF text of its pages (W116). On the scanned BS EN 1838 PDF the OCR text differs from the page
image, so expect W116 warnings there. That is the reason the source pages were also checked against page
images (see `evidence/verification-summary.json`).

Start at [the topic page](topics/lighting/escape-route-illuminance-and-duration.md).
