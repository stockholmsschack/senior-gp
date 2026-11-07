# Sanitized chess-results pages

These pages reproduce the structure that tournament 967028 (Rilton U1800
2024/2025) served on 2026-10-25. They keep the details-gate form, its
controls, the page heading, and the links that retrieval follows. They omit
player data, scripts, and styles. Each ASP.NET state value is a placeholder,
and no cookies are kept.

- `gate.html`: the tournament page behind the details gate.
- `revealed.html`: the page after the gate, with the full-details link.
- `details_gate.html`: the full-details page behind the gate again, served
  after the switch to another server.
- `details.html`: the full-details page with the tournament's `Date` row, the
  Swiss-Manager download link, and links to the other Rilton sections.
- `no_download.html`: a full-details page without a download link.

A recent tournament serves the same pages without the gates: the tournament
page as in `revealed.html`, then `details.html`.

The download body in the tests is `../rilton/rilton_u1800_2024_2025_967028.TUNX`.
