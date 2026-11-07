# tunx

This package parses Swiss-Manager `.TUNX` files. It is a Python port of the
[tunx](https://github.com/mormubis/tunx) TypeScript project, vendored into
Senior GP on 2026-10-25. It uses only the standard library. Senior GP owns this
copy, and no upstream project receives its changes.

The upstream project is MIT licensed. [LICENSE](LICENSE) holds its copyright
notice and permission notice, which must stay with this package.

`parse(content)` returns a `Tournament` or raises `ParseError`. The parser
decodes players and pairings and calculates nothing. Senior's Rilton
calculation is in `senior_gp/rilton_processor/tunx_results.py`.

## Changes from the port

The port assumed that each round holds `ceil(players / 2)` records and read
trailing sections as pairings. It also dropped results it could not decode.
This copy makes these changes:

- A round ends when every player has appeared once. A game record covers both
  players; each player without an opponent has a separate record.
- The pairings end at marker `0x4489FFD3`. Records after the last round, a
  partial round, or a missing end marker raise `ParseError`.
- Opponent `65535` with code `9` is a full-point bye (`"bye"`). Opponent
  `65534` with code `0` or `3` scores zero (`"unpaired"`).
- Code `6` is a game in which both players score zero (`"double-loss"`).
- Code `0` against a named opponent means no result yet. The pairing's
  `result` is None, and `Tournament.finished` is False.
- Ordinary wins, draws, losses, and forfeits retain codes 1–5. Unknown codes,
  invalid player numbers, duplicate players within a round, and truncated data
  raise `ParseError`. Errors include the round, player, code, or byte offset
  where available.
- `Tournament` gains `total_rounds`, `current_round` and `tiebreak_codes`. The
  tie-break codes are raw. The port's hard-coded empty `tiebreaks` list and
  `"dutch"` pairing system are removed, because the file did not supply them.
- `Player` gains `academic_title`, from player string 2.
- Errors raise `ParseError` instead of calling `on_error` and returning None.
  `ParseOptions` and `ParseWarning` are removed.
- The JSON converter script is not vendored.

The retained Rilton U1800 and U2200 files from 2024/2025 and 2025/2026, and
Rilton Cup 2024/2025, verify these layouts. Other events may use codes that
need new fixtures. See
[the parser spec](../../_spec/tunx-parser-fixes.md#implementation).
