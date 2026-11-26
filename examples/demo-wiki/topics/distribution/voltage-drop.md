---
type: topic
title: "Voltage drop limits"
sources_covered:
  - {source: dec-2024, locators: ["4.2", "Table 4-1", "4.3"], depth: raw}
  - {source: dgd-2019, locators: ["3.1", "3.2"], depth: raw}
sources_silent:
  - {source: usc-2022, reason: "covers the service point only; no voltage-drop clause (page 2 read; page 3 is tariffs)", depth: raw}
conflicts:
  - id: VD-1
    between: [dec-2024, dgd-2019]
    summary: "DEC 2024 caps the total at 4 %; DGD 2019 allows 3 % + 2 % = 5 %"
    status: resolved-by-profile
  - id: VD-2
    between: [dec-2024, dgd-2019]
    summary: "Motor starting: DEC 2024 4.3 leaves it out of the 4 % limit; only DGD 2019 3.2 gives a figure (15 %), as guidance"
    status: resolved-by-project
derived_from:
  - sources/dec-2024/ch4-voltage-drop.md
  - sources/dgd-2019/s3-cable-sizing.md
  - sources/dec-2018/ch4-voltage-drop.md
history: [dec-2018]          # superseded edition shown for history only
verification: {status: derived}
updated: 2026-11-26
---
What each source says about voltage-drop limits. Neutral page: run `edka.py view ... --profile demo-land-building`
to see which source applies there.

| Source | What it says | Page |
|---|---|---|
| [DEC 2024](../../sources/dec-2024/ch4-voltage-drop.md) | Total ≤ 4 % ("shall"); motor starting not covered | ⟦p.3⟧ ⟦p.4⟧ |
| [DGD 2019](../../sources/dgd-2019/s3-cable-sizing.md) | 3 % final + 2 % feeder ("should"); motor starting up to 15 % | ⟦p.2⟧ ⟦p.3⟧ |
| [DEC 2018](../../sources/dec-2018/ch4-voltage-drop.md) | Total ≤ 5 % (superseded edition) | ⟦p.2⟧ |

⟦src:usc-2022,dgd-2019⟧ USC 2022 is silent (see `sources_silent`). DGD's 3 % + 2 % split can share a 4 % total between feeders and
final circuits. ⟦calc⟧
