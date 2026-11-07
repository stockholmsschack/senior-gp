# Expected 2025 outputs under the phase 1 rules

> Status: **accepted.** Reviewer: bganesh · Accepted: 2026-10-25

This set applies the [scoring rules](../../_spec/senior-gp-scoring-rules.md)
decided on 2026-10-25 to the unchanged inputs of the
[2025 capture](../current-config-2025/README.md). The capture remains the
comparison baseline.

## Review

- [Clean standings](expected/output/2025-gp-standings-20261025.xlsx)
- [Validation workbook](expected/output/2025-gp-standings-validations-20261025.xlsx)
- [Structured standings](expected/standings.json)

## Reproduce

From the repository root, into a directory that does not exist:

```sh
.venv/bin/python reference-artifacts/accepted-2025/generate.py /tmp/senior-expected
.venv/bin/python reference-artifacts/accepted-2025/compare.py /tmp/senior-expected/standings.json
```

`generate.py` runs the capture's replay with the working-tree calculation. Only
`config.manager`, which the checkout no longer has, comes from the saved source. It uses retained HTTP responses and a frozen clock. If a response is missing,
it fails without accessing the network. `--normalize-missing-elo` is no longer needed.
Compare workbook contents excluding `docProps/core.xml`.

On 2026-10-28 the service regenerated both workbooks to add the first sheet,
Turneringar, which lists the counted tournaments. The class sheets keep their
accepted values and formatting. The legacy replay writes no Turneringar sheet,
so compare its class sheets only, and see the next paragraph for how they
differ now.

Later on 2026-10-28 the service regenerated both workbooks and
`standings.json` again, after the operator decided that generation counts
tournaments by date of play. The Rilton event, which starts on 27 December
2025, now comes after the three member-system events instead of before them.
Every player keeps the same rank, points and results. Two things change. A
player's name now comes from their earliest event, so 48 names in classes B
to E take the member system's spelling, such as Jussi Jakenberg for JAKENBERG
Jussi. In the workbooks, players who share a rank may appear in another
order, because ties are listed by name. `standings.json` lists players in the
order they first appear, so its player order changed throughout classes B to
E. The Turneringar
sheet lists Rilton U2200 before Rilton U1800, by date. The legacy replay
still counts Rilton first, so its names and its order of tied players differ
from these files.

The Rilton numbers here come through the retained XLS files, which are used only
as a comparison input. The phase 3 TUNX path reproduces these results in `tests/test_generation.py`.

Both workbooks now also include Spelare, a sortable table of standings participants
with FIDE ID, member ID, full name, January club membership and January standard
rating. Later joiners have blank January club and rating cells; January members
without a rating show 0. The service regenerated these workbooks from the same
retained inputs and verified that all existing worksheet contents and standings
remain unchanged. The legacy replay does not include this sheet.

## Changes from the capture

Players: A 10, B 24, C 51, D 57, E 95 (capture: E 90).

| Rule | Effect |
| --- | --- |
| Rilton eligibility at generation time | Five players added to class E: Jens Petersson (Rilton 9), Erik Wartoft (8), Daniel Enfors, Sam Alseif, Faezeh Pousaneh (penalized). Ulf Hammar and Ludwig Sandhu were already listed and gain a −1 Rilton result. Rilton points for class E players below Petersson and Wartoft fall: Eric Hjälte 9→5 (rank 4→10), Jonathan Jackmann 8→4, Mattias Kull 7→3, Anjay Prabu 6→2, Paul Omahony 5→1, Alexander Therstam 3→0, Lucas Premat 2→0. |
| Final tie-break | Equal totals now order by fewer scoring events, then share a rank; e.g. B: Oliver Nilsson and Elias Kingsley share 4th on 17. Players on zero share one rank (C 33, D 37, E 36). |
| Penalty floor `< 1800` | No change; no player has exactly 1800. |
| Duplicate January ID | No change; Eric Hjälte is class E either way. |
| DM recomputed from name | Removed; configured flags already matched. |

Run `compare.py` for the full per-player list.
