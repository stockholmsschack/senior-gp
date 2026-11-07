# Standings for Senior GP

Standings calculations for Senior GP for SSF

In the GP tournaments points are allocated 10 .. 1 whereas in the DM tournaments they are 15 .. 1

The DM tournaments are:
+ Stockholmsmästerskapet
+ Stockholmsmästerskapet i Blixt
+ Stockholmsmästerskapet i Snabbschack

GP tournaments are
+ Rilton U1800 and U2200 (not Cup): GP season Y uses the Rilton Y/(Y+1) edition.
+ Compo Cup
+ Stockholm Open
+ Stockholm Open Blixten
+ ... Rockaden Blixten etc.

The GP season names the qualification year. For example, GP 2025 uses January
2025 ratings and Rilton 2025/2026; its final takes place in 2026. A Rilton section
played entirely in January still belongs to that edition's GP season.
See [season-year rules and sources](_spec/senior-gp-season-year.md).

Ratings groups are:

- Klass A: 2200 - 
- Klass B: 2000 - 2199
- Klass C: 1800 - 1999
- Klass D: 1600 - 1799
- Klass E: - 1599

Stockholm players (district id: 5821) are separated into these ratings groups according to their ratings on Jan 1 of current calendar year.
If they do not have a ELO they are assigned 0, even if they have rapid or blitz elo

Membership can be verified by pulling ratings for district for today, if they are not present in the Jan 1 list.

Special requirements for Rilton:
--------------------------------

Rilton results are not in the member system. Senior downloads each Rilton
section's Swiss-Manager TUNX file from chess-results.com and calculates the
scores and tie-breaks itself. The file carries each player's FIDE ID, which
matches Rilton players to district members. Senior no longer needs an XLS export
from the Swiss-Manager Windows application.
See [the retrieval spec](_spec/chess-results-tunx-fetch.md) and
[the parser spec](_spec/tunx-parser-fixes.md).

Command line
------------

Install with the locked dependency versions. `uv sync` installs the `senior`
command in `.venv/bin/`, which runs from any directory:

```sh
uv sync
.venv/bin/senior --help
```

A newer `xlsxwriter` or `polars` than `uv.lock` names changes the validation
workbook's XML, so the comparison with the accepted workbook depends on the
locked versions.

To install Senior outside the checkout, build a wheel and install it with the
locked versions as constraints. The wheel holds the `senior` and `senior-web`
commands and the web application's templates, scripts, stylesheets and
catalogues:

```sh
uv build --wheel --out-dir dist
uv export --frozen --no-dev --no-emit-project --no-hashes > constraints.txt
uv venv /opt/senior
VIRTUAL_ENV=/opt/senior uv pip install -c constraints.txt dist/stsf_senior_gp-*.whl
```

The checkout no longer has the four legacy scripts in `cli/`, the four Flask
applications in `web/`, one of them the Rilton XLS upload, `examples/`,
`config/tournaments.json` or `requirements.txt`. `senior` and `senior-web`
replace them. To carry a season over from `config/tournaments.json`, enter its
tournaments in the picker or in the season's TOML file. The XLS reader in
`senior_gp/rilton_processor/excel_parser.py` stays for the TUNX parity tests.

The wheel installs only the `senior_gp` package, as Verktyg requires of tools
that share its process. It used to install `tunx`, `rating_fetcher`,
`results_processor`, `rilton_processor` and `standings_generator` as top-level
packages.

The state and output directories default to `state/` and `output/` in the
working directory. To override them, pass `--state-dir` and `--output-dir`
before the subcommand. The state directory holds each season's configuration,
in `seasons/<year>/active-configuration.toml`, and the retained inputs. The
output directory holds each season's runs in `runs/<year>/<run id>/`, and
`seasons/<year>/latest.json` names the season's latest run. A run of one
season never replaces another season's latest run. Each run holds the
standings workbook, the validation workbook, the standings data and the
generation report. Each workbook's first sheet, Turneringar, lists the
tournaments the standings count. A member-system tournament shows its ID, and
a Rilton section shows its chess-results link. Each file name ends with the UTC time at which Senior
published the run, as in `2025-gp-standings-20261025T120000Z.xlsx` and
`2025-gp-report-20261025T120000Z.json`, so all of a run's files share one suffix. The
report gives the season, the date, the configuration revision, the included
and skipped tournaments, the warnings and the names of the run's workbooks.
Senior no longer reads runs that earlier versions wrote directly in `runs/`
or in `seasons/<year>/runs/`, or the old `latest.json` beside `runs/`. Runs
left directly in `runs/` stay unlisted, but the file server still serves them
until they are deleted.

`--season YEAR`, also before the subcommand, selects the season by its GP
year. A season runs into the following spring. So, by the date in Stockholm,
the default is last year until 31 May and this year from 1 June. Each season
has its own revision. A file whose `season` differs from its directory's year
fails validation.

A `state/active-configuration.toml` saved before seasons had their own
directories moves to its season's directory on the first load, save or
listing. The move fails when the old file cannot be read, when its `season`
is not a four-digit year, or when the season's directory already has a file.
The old file then stays where it is. Every command and every overview page
reports the problem until the operator fixes or removes one of the files.

A configuration lists the season and its tournaments. The picker saves them by
date of play:

```toml
revision = 1
season = 2025

[[tournaments]]
source = "member"
id = "5366"
name = "Stockholmsmästerskapet"
scoring = "DM"
start_date = 2025-03-03

[[tournaments]]
source = "rilton"
id = "1301930"
name = "Rilton U2200"
scoring = "GP"
rating_floor = 1800
start_date = 2025-12-27
```

`start_date` is the tournament's first day of play. The member system gives a
member-system tournament's date, and the chess-results page gives a Rilton
section's date. Seasons saved before Senior stored dates have none. The next
save from the picker fills in each date it can find, as the save route below
describes.

Generation counts the tournaments in order of date of play: member-system
events by their date in the member system, and the pooled Rilton event at the
date of its earliest section. Only a Rilton event can be undated, and it then
comes last. Events on the same day count in order of ID. Generation takes a
member-system event's date from the member system when it runs, so an event
whose date has changed since it was saved counts at its new date. The first
counted event gives each player's name. Each workbook lists the tournaments in
the same order on its Turneringar sheet, and the class sheets' result columns
follow it.

- `senior validate` checks the configuration and reports every problem.
- `senior fetch-rilton TOURNAMENT` downloads and retains one configured
  Rilton section, given its chess-results ID or tournament link. A retained
  copy is kept unless `--refresh` is given.
- `senior generate` fetches the rating lists and member-system results,
  downloads each Rilton section without a retained copy, and publishes a new
  run. It prints the run directory on standard output, and its progress and
  warnings on standard error. For a season without tournaments, it makes no
  request, publishes nothing, and reports `Generation failed at configuration:
  season YYYY has no tournaments`.
- `senior generate --offline --date YYYY-MM-DD` repeats a run from the
  retained inputs without network access. To reproduce a run, `--date` must
  be the original run's date. The date decides which events have been
  played, which district list supplies later members, and the report's
  `generated_on` date. The file names carry the time of publication instead.
  Offline, a different date fails at the membership step unless an earlier run
  retained that date's rating list.
- `senior generate` without `--date` uses today's date in Stockholm for this
  year's and last year's seasons. For an older season, it uses the
  `generated_on` date in the report of the season's latest run, because
  today's district list would count members who joined after the season.
  An online run still fetches its inputs again at that date. The command refuses an older season with no such run and exits
  with status 2. When the latest run's pointer or report cannot be read, it
  exits with status 1. Either way, it publishes nothing and keeps the earlier
  run.

In the `senior` CLI, each member-system and chess-results.com request uses a
3-second connect timeout and a 15-second read timeout. These are not total
download deadlines.
Request exceptions (including timeouts) and HTTP 429 or 5xx responses trigger
up to two retries, after waits of 0.25 and 0.5 seconds. Errors while reading
a streamed TUNX body fail the download without retrying it.

Generation leaves out a tournament that cannot be retrieved or read, and names
it in the warnings. An online run does not fall back to a member-system
response retained by an earlier run. An offline run leaves out a tournament
whose response was never retained. A tournament whose response cannot be saved
is also left out. When one Rilton section cannot be retrieved or read,
generation leaves out the whole pooled Rilton event.

Other failures publish nothing and keep the earlier run. They include a failed
`--refresh-rilton` download and a failure to save a Rilton section or a rating
list. Sections are refreshed one at a time. The section whose download fails
keeps any retained copy, and sections refreshed before it keep their new
copies.
Failures exit with status 1, invalid arguments with status 2.

Retained inputs live under `<state>/inputs/`. `http/` holds each member-system
response by the SHA-256 of its URL, with a provenance file; an online run
replaces them. `rilton/<id>.TUNX` holds each Rilton section. `<id>.json`
records its source, download time, and SHA-256. It also records the start and
end dates from the first `Date` row on the pages that retrieval visits, or
`null` when no page shows a readable date.


Senior never removes a configuration or retained inputs. An online run or a
refresh replaces retained inputs, as above. All seasons share the retained
inputs. The web application's Clear downloads removes one season's runs (see
Clear downloads). `retained_seasons` in `senior_gp/seasons.py` names the
seasons whose configuration a cleanup must keep: this year and the
two years before it, and the three newest seasons with stored data. Nothing
calls it yet, because nothing removes configurations or inputs.


Web application
---------------

```sh
uv run senior-web
```

serves the operator pages on `http://127.0.0.1:9001/`, in Swedish or English.
The overview shows one season's saved configuration: the season, the number
of tournaments from each source, the revision, and the tournament picker with
the season's tournaments from both sources. The picker updates the summary
after each successful save. The overview reads and writes the same season
files as the `senior` command.
The season list offers this year and last year. With `DEVELOPMENT`, it also
offers the year before last. Without a choice, the overview shows the
default season, as `senior` does. A `season` query that names anything other
than one of the choices answers 404. The page keeps the chosen season in its
`season` query, so a reload or a change of language keeps it, and the 1 June
switch changes only the default. Without `DEVELOPMENT`, the season from two
years before leaves the choices on 1 January. A page opened for that season
before then gets 400 `invalid_input` for the field `season` from its saves,
lookups and verifications, and a reload answers 404. When the
file cannot be opened or is not valid UTF-8 TOML, the overview shows the read
error instead of the summary. When the file fails validation, the overview
lists every problem. In both cases the overview leaves out the picker. For a
season without a file, the overview says so, shows no tournaments and
revision 0, and shows an empty picker. Senior copies nothing from another
season. `--host`
and `--port` change the address. `--state-directory` and `--output-directory`
replace `state/` and `output/`, as JGP's `jgp-web` names them. The `senior`
command names the same options `--state-dir` and `--output-dir`. `--debug`
turns on Flask's debugger, restarts the server when Python code or a
catalogue changes, and sets `DEVELOPMENT`. In standalone mode, `SENIOR_FILES_PUBLIC_ORIGIN` sets the origin of
generated-file links. Its default, `http://senior.localhost:5000`, is the
origin the workspace Caddyfile serves. The workspace Caddyfile serves
`senior/output/runs`, or `SENIOR_DOWNLOAD_ROOT`, below `/downloads/` and
`/reports/` of that origin, and proxies the pages to port 9001.

### Available files and Reports

**Available files** (`/downloads`) lists the standings and validation
workbooks of every run, and **Reports** (`/reports`) lists each run's
generation report and standings data. Each row names the run's season and
the time, in Stockholm, when the run was published, newest season first and
newest run first. The rows of a season's latest run are marked **Latest
run**. The listings show every season in the output directory, not only the
seasons that the season list offers. Each link points below the files
origin, such as
`/downloads/2025/<run id>/2025-gp-standings-20261025T120000Z.xlsx`.
Senior serves no files itself. Retained inputs, configurations, operation
records and staging directories stay unlisted. Without a run, each page says
which files a generation adds. The overview links both pages below Generate,
for a host shell that replaces Senior's navigation bar.

### Clear downloads

Available files offers **Clear season YYYY downloads** for each listed season,
as JGP's Available files offers Clear downloads. A Bootstrap dialog names the
season and what goes. Cancel changes nothing. Confirming sends
`POST /api/v1/downloads/clear?season=2025`, which removes
`<output>/runs/2025/` and `<output>/seasons/2025/latest.json`. The state
directory stays as it was: configurations, retained inputs and operation
records. Other seasons' files stay too. A season older than last year then has
no latest run to take its generation date from, so it needs
`senior generate --date`. The web's Generate answers 422
`generation_date_unknown` for it.

A clear takes the generation lease, so a clear and a generation never
overlap. The route answers `{"data": {"season": 2025, "cleared": true}}`,
400 `invalid_input` without a four-digit `season`, 409 `downloads_busy` while
a generation runs, with `details.active_operation_id`, and 500
`downloads_clear_failed` when files cannot be removed. A clear of a season
without files succeeds. A generation started during a clear answers 409
`generation_busy`, with `details.operation_id` `clear-…` and
`details.operation` `null`.

### Tournament picker

The picker lists the season's tournaments by date of play, with undated
entries last. Each entry shows its source (Member system or Rilton), links to
the tournament there, and shows its first day of play, or "Date of play
unknown" without one. An added tournament takes its place by date.

The picker finds member-system tournaments by name, group, or location, or
verifies a pasted ID, and adds them to the season shown. A new tournament takes
the scoring type that its name suggests. Each member-system entry has a
scoring-type select. The operator's choice stays even when the name suggests
the other type.

A Rilton entry always scores as GP. Its rating-floor box takes the Elo below
which the section's players are penalized. A player whose January Elo equals
the floor is not penalized. An empty box means no floor, so the section
penalizes nobody. The box accepts a whole number above 0 without leading
zeros. The picker marks other text invalid and does not save it. The title
plays no part: for the 2025/2026 sections, the operator types 1800 for U2200
and leaves U1800 empty.

When the source select is set to Rilton, the picker takes a chess-results
tournament link instead. Below the link field it shows the Rilton edition
that the season uses, such as Rilton 2025/2026 for GP season 2025. The
picker verifies the link as the Rilton verification endpoint below describes,
then shows the tournament's name, dates, and edition with a rating-floor
box, an Add button, and a Cancel button. Once the box loses focus holding
text other than a floor, Add stays disabled until the text is a floor or
empty. The picker refuses a link to a tournament already in the list. A change of source,
season, language, or link discards a verification in progress or a verified
tournament not yet added, so a late answer adds nothing. An edit of the list
keeps a verification in progress from either source and a verified Rilton
tournament not yet added. A failed save keeps only the verified Rilton
tournament, and a stale-revision error discards both. If the restored list
already has the verified tournament, the picker discards the verification.

The picker saves each addition, removal, change of type, and change of floor
as soon as the operator makes it. The picker saves a floor when the box loses
focus or the operator presses Enter. After a save, the picker shows the
scoring suggestions and start dates that the server returns, and orders the
list by date again. When the latest save fails, or any save
is refused as stale, the picker shows the error and restores the list that
this page last saved. When the server refuses a new tournament as unknown,
unverified, or outside the season, the picker's error names it with its
source, name, and ID. A stale-revision error also cancels every queued save.
The operator can then no longer edit the list, and the error offers a button
that reloads the page with the same season and language. A change of season
or language waits for pending saves, then reloads the page. Before the page
closes, reloads, or follows a link, the browser asks the operator to confirm
while a save is queued or running, or while a verified Rilton tournament waits to be
added. A removal asks for confirmation and names each affected entry with its
source and ID, such as `Rilton: Rilton U1800 (1301929)`.

The picker scripts come from Flickornas. Senior adds the source, the scoring
type, the rating floor and the date of play. It identifies each entry by source
and ID, so a member-system tournament and a Rilton tournament with the same ID
are distinct.
`tests/browser/` tests the picker's state modules and the generation's
status follower under Node. `uv run pytest`
runs those tests, and skips them when Node is not installed.

### Member-system API

The picker uses two JSON endpoints to find tournaments. Each valid request
queries the member system, with the timeouts and retries in
`senior_gp/upstream.py`.

- `GET /api/v1/tournaments/search?q=<text>` returns the groups that the
  member system matches to the text, grouped by tournament, highest
  tournament ID first. `state` is `results` or `no_matches`.
- `GET /api/v1/tournaments/<id>?season=<year>` returns the tournament's
  name, start and end dates, and suggested scoring type. The suggestion is
  `DM` when the name contains `Stockholmsmästerskapet`, and `GP` otherwise.
  Without `season`, the default season applies. The endpoint accepts only a
  tournament that starts in the season's year or the following year, by its
  Stockholm date.

Errors use JGP's envelope, `{"error": {"code", "message_key", "details"}}`:

| Status | Code | Cause |
| --- | --- | --- |
| 400 | `invalid_input` | Blank search text, an ID that is not a positive integer without leading zeros, or a season outside the choices. `details.field` names the parameter. |
| 404 | `tournament_not_found` | The member system answers 404 for the ID. `details` gives `source` (`member`) and `tournament_id`. |
| 422 | `tournament_outside_season` | The tournament starts outside the window. `details` gives `source` (`member`), the ID, the season, and the start date. |
| 502 | `upstream_failure` | The member system fails after its retries, or answers with anything other than a successful JSON response with the expected fields. A lookup also fails when the response names another tournament or ends before it starts. Senior logs the cause as a warning. |

`POST /api/v1/configuration/tournaments?season=<year>` saves the season's
complete tournament list and stores it ordered by date of play. A tournament
left out of the list is removed. The body is:

```json
{"revision": 1, "tournaments": [
  {"source": "member", "tournament_id": 5366, "scoring": "DM"},
  {"source": "rilton", "tournament_id": 967027, "rating_floor": 1800}
]}
```

An entry without `source` is a member-system entry. A member-system entry needs
`scoring`, `GP` or `DM`, and takes no rating floor. A Rilton entry scores as
GP, and its `scoring` may be left out. Its `rating_floor` is a positive Elo,
or `null` or left out for no floor. Without
`season`, the default season applies. A season without a file has revision 0,
and its first save that adds a tournament creates the file.

- A tournament already in the season keeps its stored name and start date. A
  stored member-system tournament without a start date takes one from the
  member system, and a stored Rilton section takes one from its retained
  file's provenance. When the lookup fails or the provenance records none, the
  tournament stays undated and the save still succeeds.
- A new member-system tournament must pass the lookup above for the same
  season, and takes its name and start date from the member system.
- A new Rilton tournament must have been verified, as described below. It
  takes its name and start date from the retained file's provenance. When the
  provenance records a start date, the tournament must start in the season's
  window. A start date that cannot be read counts as none.

The answer gives the season's revision after the save, `changed`, and the
saved tournaments by date of play. Each has `source`, `tournament_id`, `name`,
`scoring`, `suggested_scoring`, `rating_floor` and `start_date`, an ISO date or
`null`. A Rilton entry's suggested scoring is always `GP`. A member-system
entry's floor is `null`. A list that changes nothing, not even a date or the
stored order, writes nothing. A new
member-system tournament can also fail with the lookup's 404, 422 and 502
errors. Any save can fail with:

| Status | Code | Cause |
| --- | --- | --- |
| 400 | `invalid_input` | The `season` query names a year outside the choices, and `details.field` is `season`. Or the body is not a JSON object with an integer `revision` of 0 or more and a `tournaments` list of entries that follow the rules above, with distinct source and ID pairs, and `details.field` is `tournaments`. |
| 403 | `http_403` | The host's `MUTATION_PROTECTION` returns false. |
| 409 | `stale_configuration` | The revision is not the season's stored revision. `details.current_revision` gives it. |
| 422 | `invalid_configuration` | The season's file cannot be read or fails validation, or the saved configuration would fail validation. `details.problems` lists every problem. |
| 422 | `rilton_not_verified` | A new Rilton tournament has no retained file with a readable provenance that records its title. `details` gives `source` (`rilton`) and `tournament_id`. |
| 422 | `tournament_outside_season` | A new Rilton tournament's recorded start date is outside the window. `details` gives `source` (`rilton`), the ID, the season, and the start date. |

### Rilton verification

`POST /api/v1/rilton/verify?season=2024` takes `{"url":
"https://chess-results.com/tnr967028.aspx"}`. Equivalent links, such as one
with an `s3.` server alias or other query parameters, name the same
tournament. Senior downloads the tournament's TUNX file, as `senior
fetch-rilton` does. It reads the start and end dates from the first `Date`
row on the pages it visits, normally the full-details page. When a page shows
a readable date, the tournament must start in the season's year or the
following year. Before any download, Senior reads the season's file. Senior retains the file under
`<state>/inputs/rilton/`, replacing any earlier copy, and answers with the
tournament:

```json
{"data": {"tournament": {"source": "rilton", "tournament_id": 967028,
  "name": "Rilton U1800 2024/2025", "url": "https://chess-results.com/tnr967028.aspx?lan=1",
  "start_date": "2025-01-02", "end_date": "2025-01-05", "edition": "2024/2025"}}}
```

`name` is the name in the file. `edition` is the Rilton edition that counts
for the season. Without `season`, the default season applies.

| Status | Code | Cause |
| --- | --- | --- |
| 400 | `invalid_input` | The body has no `url` string, or the link is not an https chess-results tournament link, and `details.field` is `url`. Or the `season` query names a year outside the choices, and `details.field` is `season`. |
| 403 | `http_403` | The host's `MUTATION_PROTECTION` returns false. |
| 422 | `invalid_configuration` | The season's file cannot be read or fails validation. Senior downloads nothing. `details.problems` lists every problem. |
| 422 | `tournament_outside_season` | The tournament starts outside the window. `details` gives `source` (`rilton`), the ID, the season, and the start date. |
| 500 | `retention_failed` | Senior cannot save the file or its provenance. Senior logs the cause as an error. The TUNX file may already be replaced while the provenance is not. |
| 502 | `rilton_retrieval_failed` | Retrieval fails at any stage: a page or the download cannot be fetched, the details gate misbehaves, the page offers no Swiss-Manager file, or the file is too large, unreadable, or names another tournament. `details` gives the ID, the failed `stage`, and the `cause`. Senior logs the cause as a warning. |

A 400, 422 or 502 answer retains nothing new and leaves any earlier copy.

Senior serializes saves within one process. Run it in a single worker process,
or one of two saves of the same revision may silently replace the other.

### Web generation

The overview's Generate button runs the same generation as `senior generate`
for the season shown, at today's date in Stockholm. A run fetches the rating
lists and member-system results again, downloads each Rilton section without
a retained copy, and retains what it downloads, as an online `senior
generate` does. For a season older than last year, which only `DEVELOPMENT`
offers, it generates at the date of the season's latest run.

Generate is disabled, with the reason beside it, while the season has no
saved tournaments, while a save is queued or running, after a stale save, and
while a run that the page follows is in progress. After a start, a dialog
shows the run's stage and a bar of the stages finished. The page reads the
run's status every second until the run completes or fails. The dialog then
shows the run ID, a link to Available files and any warnings, or the failed
stage and its cause. The same message stays on the page after the dialog
closes. Closing the dialog leaves the run going.

When a status read fails, the page and the dialog say that the status cannot
be read, and the page keeps reading. The next successful read shows the run
again.

The browser remembers the status URL of a running generation in
`localStorage`, under `senior:generation-operation`. It forgets the URL when
the page reads the run as completed or failed, or when the status endpoint
answers 404. A reload during the run reopens the dialog and follows the run.
Generate stays disabled until that first read answers. When the run finished
while the page was closed, the next page load shows the outcome once on the
page and leaves the dialog closed. When the first read fails for another
reason, such as a stopped server, the page says so and keeps the URL for the
next load.

When the host passes a publisher, Senior also publishes each event, from
`accepted` to `completed` or `failed`, to the operation's `topic`, after it
writes the record. With `MERCURE_PUBLIC_URL` also set, the page subscribes to
that topic there. It reads the status at once when the subscription opens and
on each message. Polling continues. A publish call that raises, or a hub that
does not answer, only loses the early reads: the run, its record and the
status endpoint behave the same. Senior logs each publish call that raises.
`publish` runs on the generation's thread, so a publisher that waits for the
hub delays the run.

One web generation runs at a time, for any season. A start that passes the
other checks while another generation runs answers 409 `generation_busy`. The
answer gives the running operation, and the page follows it instead. The
lease is `<state>/operations/generation.lease`. Its owner holds an exclusive
`flock` on it, which the kernel releases when the owning process exits. When
a start finds a lease that no process locks, Senior marks the lease's
operation failed at stage `interrupted`, removes the lease, and runs the new
start. When Senior's app is created, it does the same, and it also fails at
stage `interrupted` every other unfinished operation. After a restart, an
interrupted operation therefore reads `failed`, and a new start runs. `senior generate` takes no lease. A CLI run during a web run
publishes its own run directory, and the season's `latest.json` names
whichever run published last.

`POST /api/v1/generation/operations?season=2025` takes `{"revision": 4}`, the
revision the page shows. Senior loads that revision of the season's saved
configuration, records an operation, and answers `202` with it. The run uses
that configuration snapshot, so a later save or a change of season leaves the
run's tournaments unchanged. The run reads the retained inputs when it needs
them, so a Rilton verification during the run can replace a section's file.
`GET /api/v1/generation/operations/<operation id>` answers with the
operation's recorded state:

```json
{"data": {"operation_id": "4f…", "status_url": "/api/v1/generation/operations/4f…",
  "topic": "https://stockholmsschack.se/senior/operations/4f…", "state": "completed", "season": 2025, "configuration_revision": 4,
  "generated_on": "2026-10-25", "actor": {"email": "operator@example.org", "name": "Operator"},
  "latest_event_id": 6, "terminal": true, "run_id": "20261025T120000000000Z",
  "failure_stage": null, "events": [{"event_id": 1, "kind": "accepted",
  "message_key": "operations.accepted", "parameters": {}, "progress": {}}, "…"]}}
```

`state` is `accepted`, `running`, `completed` or `failed`. Each `stage` event
names the stage about to start: `rilton`, `membership`, `calculation` or
`publication`. Its `progress` counts the stages finished before it, such as
`{"completed": 1, "total": 4}` for `membership`. The `calculation` stage also
reads the member-system tournaments and creates the workbooks. The `completed` event gives `run_id` and the run's `warnings`.
The `failed` event gives the failed `stage` and its `detail`. The stage is
the last reported one, `starting` before the first, `scheduling` when the
run cannot be scheduled, or `interrupted`. The detail names the
failed input or step, such as `tournament 5366 (Stockholmsmästerskapet): …`.
A failure publishes nothing. The season's latest run stays.

Senior keeps each operation as `<state>/operations/<operation id>.json`, so
the record survives a restart.

| Status | Code | Cause |
| --- | --- | --- |
| 400 | `invalid_input` | The `season` query names a year outside the choices, and `details.field` is `season`. Or the body is not a JSON object with an integer `revision` of 0 or more, and `details.field` is `revision`. |
| 403 | `http_403` | The host's `MUTATION_PROTECTION` returns false. |
| 409 | `stale_configuration` | The revision is not the season's stored revision. `details.current_revision` gives it. |
| 409 | `generation_busy` | Another generation runs. `details.operation_id` names it, and `details.operation` gives its record, or `null` when Senior cannot read the record. |
| 422 | `invalid_configuration` | The season's file cannot be read or fails validation. `details.problems` lists every problem. |
| 422 | `not_generatable` | The season has no tournaments. `details` gives the `season` and the `cause`. Senior records no operation. |
| 422 | `generation_date_unknown` | The season is older than last year and has no readable latest run to take the date from. `details` gives the `season`. |
| 500 | `generation_start_failed` | The run cannot be recorded or scheduled. Senior logs the cause. When scheduling fails, Senior records the operation as failed at stage `scheduling`. |

The status endpoint answers 404 `operation_not_found` for an ID it has no
readable record for.

Mounting in a host
------------------

A host, such as the Verktyg portal, mounts Senior in its own Flask application
with `senior_gp.web.register(app, settings)`. `MANIFEST` gives the tool's `id`
(`senior`), `name`, and default `url_prefix` (`/tools/senior`). Every page and
static link follows the prefix. `tests/test_web_hosting.py` is a minimal
working host.

Registration raises `KeyError` without these settings:

- `STATE_DIRECTORY` and `OUTPUT_DIRECTORY`: the directories Senior owns.
- `FILES_PUBLIC_ORIGIN`: the origin below which the host's file server serves
  the `runs/` directory of `OUTPUT_DIRECTORY`, at both `/downloads/` and
  `/reports/`, as Verktyg's file route does for JGP and Flickornas. It may
  carry a path, or be a bare path such as Verktyg's `/files/senior`.

Senior has no public standings. Its output is the files that operators
download. Verktyg mounts Senior at `/tools/senior` and, unlike JGP and
Flickornas, serves no `/api/v1/standings/senior`.

Optional settings:

- `BASE_TEMPLATE`: the host's shell. Without it, Senior uses its bundled
  Bootstrap shell. Senior fills its `title` and `content`
  blocks and appends to its `head` and `scripts` blocks. The shell must load
  Bootstrap 5's JavaScript bundle before its `scripts` block, because the
  picker uses `bootstrap.Modal` and `bootstrap.Toast`. A shell form that leaves
  the page waits for a pending save only when it carries
  `data-senior-navigation`.
- `LOCALE`: a callable that returns `sv` or `en`. Any other value makes every
  page fail with a server error (`KeyError`). When it is set, it overrides the `lang` query, the saved cookie, and
  the browser language.
- `DEFAULT_LOCALE` (`sv`): the locale used without `LOCALE` when none of those
  names or matches `sv` or `en`. A browser wildcard (`*`) matches `sv`. A value
  other than `sv` or `en` falls back to `sv`.
- `MUTATION_PROTECTION`: a callable that takes no arguments and returns true
  when the request passes the host's CSRF check. When it returns a false
  value, Senior answers `403` to any request to one of its own routes other
  than GET, HEAD, and OPTIONS, such as the picker's save. The save sends no
  CSRF token. It is a same-origin `fetch` with `Content-Type: application/json`.
- `ACTOR`: a callable that returns the signed-in user. Without it, the actor is
  `None`. A web generation stores the value in its JSON operation record, so
  the value must be JSON-serializable. Verktyg passes the user's email and name.
- `CLOCK`: a callable that returns the current time with a time zone. It
  decides the default season and the year choices. It defaults to the system
  clock.
- `DEVELOPMENT` (false): when true, the season list also offers the year
  before last.
- `MEMBER_SYSTEM` (a live `MemberSystemDiscovery`): the
  `senior_gp.member_system.MemberSystemDiscovery` that the API endpoints
  query. Tests pass one whose `new_session` returns a fake session.
- `RILTON_FETCH` (`senior_gp.chess_results.fetch_tunx`): the callable that
  retrieves a chess-results tournament's TUNX file, given its ID. Verification
  and web generation use it. Tests pass a fake.
- `GENERATION_EXECUTOR` (a one-thread `ThreadPoolExecutor`): the executor that
  runs web generations in the background.
- `GENERATION_RUNNER` (`senior_gp.service.run_generation`): the function that
  runs one web generation. Tests pass one that answers from recorded
  responses.
- `MERCURE_PUBLISHER`: an object with the same
  `publish(topic, operation_id, status_url, transition, operation_data)`
  method as JGP's and Flickornas' publishers. It must accept Senior's topics
  and return at once. JGP's and Flickornas' `MercurePublisher` raise
  `ValueError` for a topic outside their own prefix, so neither can publish
  Senior's events. `transition` is the event, with `event_id`, `kind`, `message_key`,
  `parameters` and `progress`. `operation_data` is the operation as the status
  endpoint gives it. Topics are
  `https://stockholmsschack.se/senior/operations/<operation id>`. Senior builds
  no publisher of its own, so the standalone app only polls.
- `MERCURE_PUBLIC_URL`: the hub URL the browser subscribes at. It has no
  default, unlike JGP's `/.well-known/mercure`. Without it, or without
  `MERCURE_PUBLISHER`, the page only polls.

The host decides who reaches the prefix. Before Senior sees a request,
Verktyg's guard answers a signed-out user with `401`, or with a login
redirect for the main pages. It answers a signed-in user without access to the
tool with `403`. Senior adds no login or role of its own.

Tests
-----

`uv sync` also installs pytest. Run the tests with `uv run pytest`.
