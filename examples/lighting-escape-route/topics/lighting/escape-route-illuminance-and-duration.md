---
type: topic
title: "Escape-route emergency lighting: illuminance and duration"
sources_covered:
  - {source: sbc801-2018, locators: ["1008.2.1", "1008.3.4", "1008.3.5"], depth: raw}
  - {source: nfpa101-2018, locators: ["7.9.2.1", "7.9.2.1.1", "7.9.2.1.2", "7.9.2.1.3"], depth: raw}
  - {source: bs-en1838-1999, locators: ["4.2.1", "4.2.2", "4.2.5"], depth: raw}
  - {source: bs5266-1-1999, locators: ["5.3.2"], depth: raw}
  - {source: sll-lg12-2015, locators: ["3.4.2", "7"], depth: raw}
sources_silent:
  - {source: sbc401-2024, reason: "56-0.9.4 (p.416) defers to ISO 30061 and gives no illuminance or duration; its Annex A.56 tables have no text layer and were not read", depth: raw}
conflicts:
  - id: EL-1
    between: [sbc801-2018, nfpa101-2018]
    summary: "Rounding of the same requirement: 11 / 1 lux (SBC) vs 10.8 / 1.1 lux (NFPA). SBC is higher on the average, NFPA on the initial minimum."
    status: resolved-by-profile
  - id: EL-2
    between: [sbc801-2018, bs-en1838-1999]
    summary: "Different measures: SBC sets an average along the egress path (11 lux); EN 1838 sets a centre-line minimum (1 lx). Meeting one does not show the other."
    status: resolved-by-profile
  - id: EL-3
    between: [bs5266-1-1999, bs-en1838-1999]
    summary: "BS 5266-1:1999 allows 0.2 lx (preferably 1 lx) on the centre line; EN 1838 and LG12 2015 require 1 lx. Later BS 5266-1 editions are not registered here."
    status: accepted-difference
  - id: EL-4
    between: [sbc801-2018, nfpa101-2018, sll-lg12-2015, bs-en1838-1999]
    summary: "Duration: 90 minutes (SBC), 1½ hours (NFPA), normally 3 hours (LG12), 1 h (EN 1838)."
    status: resolved-by-profile
derived_from:
  - sources/sbc801-2018/1008-egress-illumination.md
  - sources/sbc401-2024/56-0-9-4-illumination-systems.md
  - sources/nfpa101-2018/7-9-emergency-lighting.md
  - sources/bs-en1838-1999/4-2-escape-routes.md
  - sources/bs5266-1-1999/5-3-2-escape-route-illuminance.md
  - sources/sll-lg12-2015/3-4-escape-routes-and-7-duration.md
verification: {status: derived}
updated: 2026-11-26
---
What each source says about emergency lighting of escape routes. This page is neutral: it does not say
which source applies. For a given project run, for example:

```
python tools/edka.py view examples/lighting-escape-route topics/lighting/escape-route-illuminance-and-duration.md --profile saudi-new-building
python tools/edka.py view examples/lighting-escape-route topics/lighting/escape-route-illuminance-and-duration.md --profile us-ahj-nfpa101-2018
```

## Illuminance

| Source | Measure | Value | Page |
|---|---|---|---|
| [SBC 801 1008.3.5](../../sources/sbc801-2018/1008-egress-illumination.md) | average / minimum along egress path, initial → end of duration | 11 / 1 lux → 6 / 0.6 lux; max:min ≤ 40 to 1 | ⟦p.230⟧ |
| [NFPA 101 7.9.2.1.1-3](../../sources/nfpa101-2018/7-9-emergency-lighting.md) | average / any point, initial → end of 1½ h | 10.8 / 1.1 lux → 6.5 / 0.65 lux; max:min ≤ 40 to 1 | ⟦p.314⟧ |
| [BS EN 1838 4.2.1-2](../../sources/bs-en1838-1999/4-2-escape-routes.md) | centre line; central band 50 % of it | 1 lx; ≤ 40:1 on the centre line | ⟦p.6⟧ ⟦p.7⟧ |
| [BS 5266-1:1999 5.3.2](../../sources/bs5266-1-1999/5-3-2-escape-route-illuminance.md) | centre line (UK deviation) | 0.2 lx, preferably 1 lx | ⟦p.7⟧ |
| [SLL LG12 3.4.2](../../sources/sll-lg12-2015/3-4-escape-routes-and-7-duration.md) | centre line / centre band | 1 lx / 0.5 lx | ⟦p.15⟧ |

## Duration

| Source | Value | Page |
|---|---|---|
| [SBC 801 1008.3.4](../../sources/sbc801-2018/1008-egress-illumination.md) | 90 minutes | ⟦p.230⟧ |
| [NFPA 101 7.9.2.1](../../sources/nfpa101-2018/7-9-emergency-lighting.md) | 1½ hours | ⟦p.314⟧ |
| [BS EN 1838 4.2.5](../../sources/bs-en1838-1999/4-2-escape-routes.md) | 1 h | ⟦p.7⟧ |
| [SLL LG12 7](../../sources/sll-lg12-2015/3-4-escape-routes-and-7-duration.md) | normally 3 hours; always for sleeping risk and places of entertainment | ⟦p.41⟧ |

⟦src:sbc801-2018,nfpa101-2018⟧ 90 minutes = 1½ hours, so SBC 801 and NFPA 101 agree on duration. ⟦calc⟧

⟦src:sbc801-2018,nfpa101-2018⟧ A design that must satisfy both SBC 801 and NFPA 101 (for example a client checklist written in NFPA
figures) takes the higher of each pair: 11 lux average and 1.1 lux minimum.
