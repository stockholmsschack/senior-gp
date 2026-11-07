# Current configuration reference: 2025

Captured on 2026-10-25. These are review artifacts, not an approved golden baseline.

## Workbooks

- [Clean standings](adjusted-reference/output/2025-gp-standings-20261025.xlsx)
- [Validation workbook](adjusted-reference/output/2025-gp-standings-validations-20261025.xlsx)
- [Generation log](adjusted-reference/generation.log)
- [Structured standings](adjusted-reference/standings.json)
- [Replay verification](validation.json)

The output contains 232 players: A 10, B 24, C 51, D 57, E 90.
It includes the three configured member-system tournaments and the legacy
combined Rilton result. Configuration remained unchanged during generation.

## Inputs and provenance

`inputs/tournaments.json` is the original configuration: Compo Cup 5382 (GP),
Stockholmsmästerskapet 5366 (DM), and Stockholmsmästerskapet i blixt 5383 (DM).

`inputs/http/` contains raw response bodies and URL, retrieval time, status,
content type, and SHA-256 metadata. This includes January 2025 district ratings,
the 2026-10-25 district list, tournament metadata, and each fetched group table.
Request credentials and cookies are not retained.

`inputs/rilton/` retains all seven supplied files: four XLS files covering
2024/2025 and 2025/2026, plus the three 2025/2026 TUNX fixtures. Generation used
the 2025/2026 XLS pair. TUNX files were retained for later parser comparisons;
this capture does not establish TUNX calculation parity.

`source/` holds the unchanged working-tree calculation packages and configuration,
plus dependency metadata. `metadata.json` records the Git revision, installed
package versions, and capture clock. The working tree contained uncommitted
changes, so the saved source, rather than the Git revision alone, defines this run.
`checksums.json` records hashes of the retained files, excluding Python caches
and the checksum manifest itself.

## Limitations requiring review

1. **Unmodified generation fails.** The January response has one player with
   `elo: null`. The current classifier raises `Invalid elo data structure` at
   record 904. `baseline/generation.log` retains progress before that exception.
   The separate `adjusted-reference` run maps missing/null Elo to an empty
   mapping before classification, yielding zero under the documented rule.
   `normalization.json` identifies the affected member. Raw inputs and saved
   application source are unchanged. No other calculation adjustment was made.
2. **Rilton season clarification, resolved 2026-10-25.** GP 2025 uses Rilton
   2025/2026, so this capture uses the correct edition. The old README confused
   the GP season with the following calendar year in which its final is held.
   See the [verified season rule](../../_spec/senior-gp-season-year.md).
   The reference inputs and workbooks remain unchanged.
3. **Membership depends on the capture date.** The current pipeline supplements
   January 2025 membership with the 2026-10-25 list and assigns the 718 additional
   member IDs to class E for member-system results. This is not a historical
   2025 membership cutoff. Rilton matching uses the January list only.
4. **Duplicate January identity.** The response contains 2,809 records and 2,808
   distinct member IDs. Existing dictionary behavior is preserved.
5. **Current ranking behavior is preserved.** Final ties inherit existing order;
   Rilton penalties and allocation retain current behavior. Human acceptance
   and the phase 1 rule decisions remain outstanding.

`capture/` contains the initial sandbox-blocked attempt. `baseline/` contains
the subsequent unmodified attempt that stopped at null Elo. Neither is a
successful output set; use `adjusted-reference/output/` for review.

## Offline replay

From the repository root, using the current virtual environment:

```sh
.venv/bin/python reference-artifacts/current-config-2025/reproduce.py /tmp/senior-reference-replay --normalize-missing-elo
```

Choose an output directory that does not exist. The script uses the saved source,
copies the original configuration, freezes date-dependent calls to the capture
clock, and intercepts HTTP calls with retained responses. A missing response fails
without accessing the network. Omitting `--normalize-missing-elo` reproduces the
original classifier failure. `--capture` permits fetching missing responses and
is intended only for capture, not regression replay.

One offline replay passed. Structured standings were byte-identical, and every
ZIP member in both workbooks matched except the excluded creation-time metadata
in `docProps/core.xml`. This includes sheet content, ordering, styles, and number
formats. No application tests or production code changes were needed.
