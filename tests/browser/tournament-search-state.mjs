import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const moduleSource = await readFile(
    new URL(
        "../../senior_gp/web/static/js/tournament-search-state.js",
        import.meta.url,
    ),
    "utf8",
);
const {
    MINIMUM_TOURNAMENT_SEARCH_LENGTH,
    tournamentKey,
    tournamentLookupUrl,
    tournamentSearchPresentation,
    TournamentSelectionState,
    TournamentSearchState,
    tournamentSearchUrl,
} = await import(
    `data:text/javascript;base64,${Buffer.from(moduleSource).toString("base64")}`
);

function controlledScheduler() {
    const pending = new Map();
    let nextId = 0;
    return {
        schedule(callback) {
            nextId += 1;
            pending.set(nextId, callback);
            return nextId;
        },
        cancel(id) {
            pending.delete(id);
        },
        runAll() {
            const callbacks = [...pending.values()];
            pending.clear();
            callbacks.forEach((callback) => callback());
        },
        get size() {
            return pending.size;
        },
    };
}

function deferred() {
    let resolve;
    const promise = new Promise((resolvePromise) => {
        resolve = resolvePromise;
    });
    return { promise, resolve };
}

async function settle() {
    await Promise.resolve();
    await Promise.resolve();
}

function canonical(tournamentId, name, suggestedScoring = "GP") {
    return {
        tournament_id: tournamentId,
        name,
        start_date: "2025-09-06",
        end_date: "2025-09-07",
        suggested_scoring: suggestedScoring,
    };
}

// Each helper defaults to the date of its source's verified fixture: canonical() or verifiedRilton().
function member(tournamentId, name, scoring = "GP", suggestedScoring = scoring, startDate = "2025-09-06") {
    return {
        source: "member",
        tournament_id: tournamentId,
        name,
        scoring,
        suggested_scoring: suggestedScoring,
        rating_floor: null,
        start_date: startDate,
    };
}

function rilton(tournamentId, name, ratingFloor = null, startDate = "2025-01-02") {
    return {
        source: "rilton",
        tournament_id: tournamentId,
        name,
        scoring: "GP",
        suggested_scoring: "GP",
        rating_floor: ratingFloor,
        start_date: startDate,
    };
}

function verifiedRilton(tournamentId, name) {
    return {
        source: "rilton",
        tournament_id: tournamentId,
        name,
        url: `https://chess-results.com/tnr${tournamentId}.aspx?lan=1`,
        start_date: "2025-01-02",
        end_date: "2025-01-05",
        edition: "2025/2026",
    };
}

function selectedIds(machine) {
    return machine.state.selectedTournaments.map(
        (tournament) => tournament.tournament_id,
    );
}

assert.equal(MINIMUM_TOURNAMENT_SEARCH_LENGTH, 3);
assert.equal(
    tournamentLookupUrl(
        5382,
        "/api/v1/tournaments/__tournament_id__?season=2025",
    ),
    "/api/v1/tournaments/5382?season=2025",
);
assert.equal(
    tournamentSearchUrl(
        "Senior DM/Öppen & final",
        "/api/v1/tournaments/search",
    ),
    "/api/v1/tournaments/search?q=Senior%20DM%2F%C3%96ppen%20%26%20final",
);
assert.deepEqual(
    [
        { status: "idle", query: "", tournaments: [] },
        { status: "idle", query: "ab", tournaments: [] },
        { status: "loading", query: "abc", tournaments: [] },
        { status: "empty", query: "abc", tournaments: [] },
        {
            status: "failure",
            query: "abc",
            tournaments: [],
            errorMessageKey: "errors.member_system.unavailable",
        },
        { status: "results", query: "abc", tournaments: [{}, {}] },
    ].map((state) => tournamentSearchPresentation(state)),
    [
        { messageKey: "tournament_search.idle", parameters: {}, tone: "quiet" },
        { messageKey: "tournament_search.minimum", parameters: {}, tone: "quiet" },
        { messageKey: "tournament_search.loading", parameters: {}, tone: "quiet" },
        { messageKey: "tournament_search.empty", parameters: {}, tone: "empty" },
        {
            messageKey: "errors.member_system.unavailable",
            parameters: {},
            tone: "failure",
        },
        {
            messageKey: "tournament_search.results",
            parameters: { count: 2 },
            tone: "quiet",
        },
    ],
);

// The default scheduler debounces with the browser's timer.
{
    const originalSetTimeout = globalThis.setTimeout;
    const originalClearTimeout = globalThis.clearTimeout;
    let scheduledCallback;
    let scheduledDelay;

    globalThis.setTimeout = function browserSetTimeout(callback, delay) {
        assert.equal(this, globalThis);
        scheduledCallback = callback;
        scheduledDelay = delay;
        return 1;
    };
    globalThis.clearTimeout = function browserClearTimeout() {
        assert.equal(this, globalThis);
    };

    try {
        const machine = new TournamentSearchState({
            search: async () => ({ tournaments: [] }),
        });

        machine.setSearchText("was");
        assert.equal(scheduledDelay, 300);
        scheduledCallback();
        await settle();
        assert.equal(machine.state.status, "empty");
    } finally {
        globalThis.setTimeout = originalSetTimeout;
        globalThis.clearTimeout = originalClearTimeout;
    }
}

// Short text sends nothing, and only the last text in the debounce period is searched.
{
    const scheduler = controlledScheduler();
    const searches = [];
    const states = [];
    const machine = new TournamentSearchState({
        search: async (query) => {
            searches.push(query);
            return { tournaments: [] };
        },
        onChange: (state) => states.push(state.status),
        schedule: scheduler.schedule,
        cancel: scheduler.cancel,
    });

    machine.setSearchText(" ab ");
    assert.equal(scheduler.size, 0);
    assert.equal(machine.state.status, "idle");
    machine.setSearchText(" abc ");
    machine.setSearchText(" abcd ");
    assert.equal(scheduler.size, 1);
    assert.deepEqual(searches, []);
    assert.equal(machine.state.status, "loading");
    scheduler.runAll();
    await settle();
    assert.deepEqual(searches, ["abcd"]);
    assert.equal(machine.state.status, "empty");
    assert.deepEqual(states, ["idle", "loading", "loading", "empty"]);

    machine.setSearchText("another");
    assert.equal(scheduler.size, 1);
    machine.clear();
    assert.equal(scheduler.size, 0);
    assert.equal(machine.state.status, "idle");
    assert.equal(machine.state.searchText, "");
    assert.deepEqual(machine.state.tournaments, []);
}

// A response to older text is ignored.
{
    const scheduler = controlledScheduler();
    const first = deferred();
    const second = deferred();
    const responses = new Map([
        ["first", first.promise],
        ["second", second.promise],
    ]);
    const machine = new TournamentSearchState({
        search: (query) => responses.get(query),
        schedule: scheduler.schedule,
        cancel: scheduler.cancel,
    });

    machine.setSearchText("first");
    scheduler.runAll();
    machine.setSearchText("second");
    scheduler.runAll();
    second.resolve({
        tournaments: [{ tournament_id: 2, name: "New result" }],
    });
    await settle();
    assert.equal(machine.state.status, "results");
    assert.equal(machine.state.tournaments[0].tournament_id, 2);

    first.resolve({
        tournaments: [{ tournament_id: 1, name: "Stale result" }],
    });
    await settle();
    assert.equal(machine.state.tournaments[0].tournament_id, 2);
    assert.equal(machine.state.searchText, "second");
}

// The previous results stay visible while the next search loads.
{
    const scheduler = controlledScheduler();
    const nextResults = deferred();
    let searchCount = 0;
    const previousTournaments = [
        { tournament_id: 1, name: "Previous result" },
    ];
    const machine = new TournamentSearchState({
        search: async () => {
            searchCount += 1;
            if (searchCount === 1) {
                return { tournaments: previousTournaments };
            }
            return nextResults.promise;
        },
        schedule: scheduler.schedule,
        cancel: scheduler.cancel,
    });

    machine.setSearchText("first");
    scheduler.runAll();
    await settle();
    assert.equal(machine.state.status, "results");

    machine.setSearchText("second");
    assert.equal(machine.state.status, "loading");
    assert.equal(machine.state.tournaments, previousTournaments);

    scheduler.runAll();
    assert.equal(machine.state.status, "loading");
    assert.equal(machine.state.tournaments, previousTournaments);

    nextResults.resolve({ tournaments: [] });
    await settle();
    assert.equal(machine.state.status, "empty");
    assert.deepEqual(machine.state.tournaments, []);
}

// A failed search shows the server's message.
{
    const scheduler = controlledScheduler();
    const machine = new TournamentSearchState({
        search: async () => {
            const error = new Error("unavailable");
            error.messageKey = "errors.member_system.unavailable";
            throw error;
        },
        schedule: scheduler.schedule,
        cancel: scheduler.cancel,
    });

    machine.setSearchText("failure");
    scheduler.runAll();
    await settle();
    assert.equal(machine.state.status, "failure");
    assert.equal(
        machine.state.errorMessageKey,
        "errors.member_system.unavailable",
    );
}

// Selecting a search result verifies it and adds the canonical tournament with its suggested scoring type.
{
    const lookupResponse = deferred();
    const lookupIds = [];
    const states = [];
    const machine = new TournamentSelectionState({
        lookup(tournamentId) {
            lookupIds.push(tournamentId);
            return lookupResponse.promise;
        },
        onChange: (state) => states.push(state.status),
    });

    const selection = machine.selectSearchResult({
        tournament_id: 5366,
        name: "Unverified search name",
        matching_groups: [{ group_id: 8101, name: "Grupp A" }],
    });

    assert.deepEqual(lookupIds, [5366]);
    assert.equal(machine.state.status, "verifying");
    assert.equal(machine.state.verifiedTournament, null);

    lookupResponse.resolve({
        tournament: canonical(5366, "Stockholmsmästerskapet", "DM"),
    });
    await selection;

    assert.deepEqual(states, ["verifying", "verified"]);
    assert.deepEqual(
        machine.state.verifiedTournament,
        canonical(5366, "Stockholmsmästerskapet", "DM"),
    );
    assert.deepEqual(machine.state.selectedTournaments, [
        member(5366, "Stockholmsmästerskapet", "DM"),
    ]);
}

// A pasted ID is trimmed and verified. Text that is not a positive integer, and a search result without an ID, are refused without a lookup.
{
    const lookupIds = [];
    const machine = new TournamentSelectionState({
        lookup: async (tournamentId) => {
            lookupIds.push(tournamentId);
            return { tournament: canonical(tournamentId, "Pasted") };
        },
    });

    await machine.verifyTournamentId(" 7447 ");
    assert.deepEqual(lookupIds, [7447]);
    assert.equal(machine.state.status, "verified");
    assert.deepEqual(selectedIds(machine), [7447]);

    for (const value of ["not-an-id", "012", "0", "1.5"]) {
        await machine.verifyTournamentId(value);
        assert.equal(machine.state.status, "failure");
        assert.equal(
            machine.state.errorMessageKey,
            "errors.tournament_lookup.invalid_input",
        );
    }
    await machine.selectSearchResult({ group_id: 8101, name: "Group only" });
    assert.deepEqual(lookupIds, [7447]);
    assert.deepEqual(selectedIds(machine), [7447]);
}

// A lookup answer for another tournament, a bad date, or an unknown scoring type is refused.
for (const tournament of [
    canonical(9999, "Mismatched"),
    { ...canonical(5382, "Bad date"), start_date: "2025-02-30" },
    { ...canonical(5382, "Ends first"), end_date: "2025-09-05" },
    { ...canonical(5382, "Unknown type"), suggested_scoring: "SM" },
]) {
    const machine = new TournamentSelectionState({
        lookup: async () => ({ tournament }),
    });

    await machine.verifyTournamentId(5382);
    assert.equal(machine.state.status, "failure");
    assert.equal(machine.state.verifiedTournament, null);
    assert.deepEqual(machine.state.selectedTournaments, []);
}

// The server's refusal, such as a tournament outside the season, is shown and adds nothing.
{
    const machine = new TournamentSelectionState({
        lookup: async () => {
            const error = new Error("outside");
            error.messageKey = "errors.tournament_lookup.outside_season";
            throw error;
        },
    });

    await machine.verifyTournamentId(5382);
    assert.equal(machine.state.status, "failure");
    assert.equal(
        machine.state.errorMessageKey,
        "errors.tournament_lookup.outside_season",
    );
    assert.deepEqual(machine.state.selectedTournaments, []);
}

// A lookup answered after the operator moved on adds nothing.
{
    const lookupResponse = deferred();
    const machine = new TournamentSelectionState({
        lookup: () => lookupResponse.promise,
    });

    const selection = machine.verifyTournamentId(5382);
    machine.clear();
    lookupResponse.resolve({ tournament: canonical(5382, "Late answer") });
    await selection;
    assert.equal(machine.state.status, "idle");
    assert.deepEqual(machine.state.selectedTournaments, []);
}

// Tournaments are ordered by date of play, whatever order they are added in, and a duplicate is refused.
{
    const dates = { 100: "2025-11-01", 200: "2025-03-01" };
    const machine = new TournamentSelectionState({
        lookup: async (tournamentId) => ({
            tournament: {
                ...canonical(tournamentId, `Tournament ${tournamentId}`),
                start_date: dates[tournamentId],
                end_date: dates[tournamentId],
            },
        }),
        initialTournaments: [
            member(300, "Stored", "GP", "GP", "2025-06-01"),
            member(400, "Undated", "GP", "GP", null),
        ],
    });

    await machine.verifyTournamentId(100);
    await machine.verifyTournamentId(200);
    assert.deepEqual(selectedIds(machine), [200, 300, 100, 400]);

    await machine.verifyTournamentId(100);
    assert.equal(machine.state.status, "failure");
    assert.equal(
        machine.state.errorMessageKey,
        "errors.tournament_selection.duplicate",
    );
    assert.deepEqual(selectedIds(machine), [200, 300, 100, 400]);

    assert.equal(machine.removeTournament("member:100"), true);
    assert.equal(machine.state.status, "idle");
    assert.deepEqual(selectedIds(machine), [200, 300, 400]);
    assert.equal(machine.removeTournament("member:999"), false);
    assert.equal(machine.removeTournament("rilton:200"), false);
    assert.equal(machine.removeAllTournaments(), true);
    assert.deepEqual(machine.state.selectedTournaments, []);
    assert.equal(machine.removeAllTournaments(), false);
}

// An explicit scoring type stays, even when the name suggests another.
{
    const machine = new TournamentSelectionState({
        lookup: async (tournamentId) => ({
            tournament: canonical(tournamentId, "Stockholmsmästerskapet", "DM"),
        }),
        initialTournaments: [member(5366, "Stockholmsmästerskapet", "GP", "DM")],
    });

    await machine.verifyTournamentId(5366);
    assert.equal(machine.state.selectedTournaments[0].scoring, "GP");

    assert.equal(machine.setScoring("member:5366", "GP"), false);
    assert.equal(machine.setScoring("member:999", "DM"), false);
    assert.equal(machine.setScoring("member:5366", "DM"), true);
    assert.equal(machine.state.selectedTournaments[0].scoring, "DM");
    assert.throws(() => machine.setScoring("member:5366", "SM"));
}

// A member-system tournament and a Rilton tournament with the same ID are distinct, and a lookup adds the member-system one.
{
    const machine = new TournamentSelectionState({
        lookup: async (tournamentId) => ({
            tournament: canonical(tournamentId, "Member event"),
        }),
        initialTournaments: [rilton(967028, "Rilton U1800 2024/2025")],
    });

    await machine.verifyTournamentId(967028);
    assert.equal(machine.state.status, "verified");
    assert.deepEqual(
        machine.state.selectedTournaments.map(tournamentKey),
        ["rilton:967028", "member:967028"],
    );
    assert.equal(machine.removeTournament("rilton:967028"), true);
    assert.deepEqual(
        machine.state.selectedTournaments.map(tournamentKey),
        ["member:967028"],
    );
}

// A Rilton section always scores as GP, and only a Rilton section has a rating floor.
{
    const changes = [];
    const machine = new TournamentSelectionState({
        lookup: async () => ({}),
        initialTournaments: [
            rilton(967027, "Rilton U2200"),
            member(5382, "Senior GP"),
        ],
        onChange: (state) => changes.push(state.selectedTournaments),
    });

    assert.equal(machine.setScoring("rilton:967027", "DM"), false);
    assert.equal(machine.setRatingFloor("member:5382", 1600), false);
    assert.equal(machine.setRatingFloor("rilton:967027", null), false);
    assert.equal(changes.length, 0);

    assert.equal(machine.setRatingFloor("rilton:967027", 1700), true);
    assert.equal(machine.state.selectedTournaments[0].rating_floor, 1700);
    assert.equal(machine.setRatingFloor("rilton:967027", null), true);
    assert.equal(machine.state.selectedTournaments[0].rating_floor, null);
    for (const floor of [0, -100, 1.5, "1800", "none", undefined]) {
        assert.throws(() => machine.setRatingFloor("rilton:967027", floor));
    }
}

// Suggestions from a save replace the shown ones, keep the operator's choices, and do not abandon a pending lookup.
{
    const lookupResponse = deferred();
    const machine = new TournamentSelectionState({
        lookup: () => lookupResponse.promise,
        initialTournaments: [
            rilton(967027, "Rilton U2200", 2000),
            member(5366, "Stockholmsmästerskapet", "GP", "DM"),
        ],
    });

    const verification = machine.verifyTournamentId(5382);
    machine.updateSuggestions([
        rilton(967027, "Rilton U2200"),
        member(5366, "Stockholmsmästerskapet", "DM", "GP"),
    ]);
    assert.equal(machine.state.status, "verifying");
    assert.deepEqual(machine.state.selectedTournaments, [
        rilton(967027, "Rilton U2200", 2000),
        member(5366, "Stockholmsmästerskapet", "GP", "GP"),
    ]);

    lookupResponse.resolve({ tournament: canonical(5382, "Senior GP") });
    await verification;
    assert.equal(machine.state.status, "verified");
    assert.deepEqual(selectedIds(machine), [967027, 5366, 5382]);
}

// A date that a save finds for an undated tournament moves it into date order.
{
    const machine = new TournamentSelectionState({
        lookup: async () => ({}),
        initialTournaments: [
            member(5382, "Compo Cup", "GP", "GP", "2025-03-21"),
            member(5366, "Stockholmsmästerskapet", "DM", "DM", null),
        ],
    });

    machine.updateSuggestions([
        member(5382, "Compo Cup", "GP", "GP", "2025-03-21"),
        member(5366, "Stockholmsmästerskapet", "DM", "DM", "2025-03-03"),
    ]);
    assert.deepEqual(selectedIds(machine), [5366, 5382]);
    assert.equal(machine.state.selectedTournaments[0].start_date, "2025-03-03");
}

// Invalid stored tournaments are refused.
for (const tournament of [
    member(0, "Zero"),
    member(1, " "),
    { ...member(1, "No type"), scoring: undefined },
    { ...member(1, "No source"), source: undefined },
    { ...rilton(1, "Rilton"), scoring: "DM" },
    { ...rilton(1, "Rilton"), rating_floor: 0 },
    { ...rilton(1, "Rilton"), rating_floor: "none" },
]) {
    assert.throws(() => new TournamentSelectionState({
        lookup: async () => ({}),
        initialTournaments: [tournament],
    }));
}

// A verified Rilton tournament waits for the operator and is added with the chosen floor, in date order.
{
    const urls = [];
    const machine = new TournamentSelectionState({
        lookup: async () => ({}),
        verifyRilton: async (url) => {
            urls.push(url);
            return { tournament: verifiedRilton(967028, "Rilton U1800 2024/2025") };
        },
        initialTournaments: [member(5382, "Senior GP")],
    });

    await machine.verifyRiltonUrl(" https://chess-results.com/tnr967028.aspx ");
    assert.deepEqual(urls, ["https://chess-results.com/tnr967028.aspx"]);
    assert.equal(machine.state.status, "pending_addition");
    assert.deepEqual(machine.state.verifiedTournament, verifiedRilton(967028, "Rilton U1800 2024/2025"));
    assert.deepEqual(selectedIds(machine), [5382]);

    assert.equal(machine.addVerifiedRilton(null), true);
    assert.equal(machine.state.status, "idle");
    assert.deepEqual(machine.state.selectedTournaments, [
        rilton(967028, "Rilton U1800 2024/2025"),
        member(5382, "Senior GP"),
    ]);
    assert.equal(machine.addVerifiedRilton(null), false);

    // The same tournament from an equivalent link is a duplicate.
    await machine.verifyRiltonUrl("https://s3.chess-results.com/tnr967028.aspx?lan=6");
    assert.equal(machine.state.status, "failure");
    assert.equal(machine.state.errorMessageKey, "errors.tournament_selection.duplicate");
    assert.equal(machine.state.selectedTournaments.length, 2);
}

// A verified Rilton tournament is added with the typed floor, and an invalid floor is refused.
{
    const machine = new TournamentSelectionState({
        lookup: async () => ({}),
        verifyRilton: async () => ({ tournament: verifiedRilton(1301930, "Rilton U2200 2025/2026") }),
    });

    await machine.verifyRiltonUrl("https://chess-results.com/tnr1301930.aspx");
    for (const floor of [0, "1800", "none", undefined]) {
        assert.throws(() => machine.addVerifiedRilton(floor));
    }
    assert.equal(machine.state.status, "pending_addition");

    assert.equal(machine.addVerifiedRilton(1800), true);
    assert.deepEqual(machine.state.selectedTournaments, [
        rilton(1301930, "Rilton U2200 2025/2026", 1800),
    ]);
}

// A verification answered after a change of source, or of season, adds nothing.
{
    const answer = deferred();
    const machine = new TournamentSelectionState({
        lookup: async () => ({}),
        verifyRilton: () => answer.promise,
    });

    const verification = machine.verifyRiltonUrl("https://chess-results.com/tnr967028.aspx");
    assert.equal(machine.state.status, "verifying");
    machine.clear();
    answer.resolve({ tournament: verifiedRilton(967028, "Rilton U1800 2024/2025") });
    await verification;
    assert.equal(machine.state.status, "idle");
    assert.equal(machine.state.verifiedTournament, null);
    assert.equal(machine.addVerifiedRilton(null), false);
    assert.deepEqual(machine.state.selectedTournaments, []);
}

// A pending Rilton tournament is discarded when the operator moves on.
{
    const machine = new TournamentSelectionState({
        lookup: async () => ({}),
        verifyRilton: async () => ({ tournament: verifiedRilton(967028, "Rilton U1800 2024/2025") }),
    });

    await machine.verifyRiltonUrl("https://chess-results.com/tnr967028.aspx");
    machine.clear();
    assert.equal(machine.addVerifiedRilton(null), false);
    assert.deepEqual(machine.state.selectedTournaments, []);
}

// An empty link is refused without a request, and the server's refusal is shown.
{
    let requests = 0;
    const machine = new TournamentSelectionState({
        lookup: async () => ({}),
        verifyRilton: async () => {
            requests += 1;
            const error = new Error("no download");
            error.messageKey = "errors.rilton.no_download";
            throw error;
        },
        initialTournaments: [member(5382, "Senior GP")],
    });

    await machine.verifyRiltonUrl("  ");
    assert.equal(requests, 0);
    assert.equal(machine.state.errorMessageKey, "errors.rilton.invalid_url");

    await machine.verifyRiltonUrl("https://chess-results.com/tnr967028.aspx");
    assert.equal(requests, 1);
    assert.equal(machine.state.status, "failure");
    assert.equal(machine.state.errorMessageKey, "errors.rilton.no_download");
    assert.deepEqual(selectedIds(machine), [5382]);
}

// A verification answer that is not a valid Rilton tournament is refused.
for (const tournament of [
    { ...verifiedRilton(967028, "Rilton"), source: "member" },
    { ...verifiedRilton(967028, " ") },
    { ...verifiedRilton(967028, "Rilton"), end_date: null },
    { ...verifiedRilton(967028, "Rilton"), end_date: "2025-01-01" },
]) {
    const machine = new TournamentSelectionState({
        lookup: async () => ({}),
        verifyRilton: async () => ({ tournament }),
    });

    await machine.verifyRiltonUrl("https://chess-results.com/tnr967028.aspx");
    assert.equal(machine.state.status, "failure");
    assert.equal(machine.state.errorMessageKey, "errors.rilton.unavailable");
    assert.deepEqual(machine.state.selectedTournaments, []);
}

// A Rilton tournament whose page shows no dates is accepted.
{
    const machine = new TournamentSelectionState({
        lookup: async () => ({}),
        verifyRilton: async () => ({
            tournament: { ...verifiedRilton(967028, "Rilton"), start_date: null, end_date: null },
        }),
    });

    await machine.verifyRiltonUrl("https://chess-results.com/tnr967028.aspx");
    assert.equal(machine.state.status, "pending_addition");
    assert.equal(machine.state.verifiedTournament.start_date, null);
}

// An edit of the list, or a failed save that restores the saved list, keeps
// a verified Rilton tournament waiting, unless the new list already has it.
{
    const machine = new TournamentSelectionState({
        lookup: async () => ({}),
        verifyRilton: async () => ({ tournament: verifiedRilton(967028, "Rilton U1800 2024/2025") }),
        initialTournaments: [member(5382, "Senior GP")],
    });

    await machine.verifyRiltonUrl("https://chess-results.com/tnr967028.aspx");
    assert.equal(machine.setScoring(tournamentKey(member(5382, "Senior GP")), "DM"), true);
    assert.equal(machine.state.status, "pending_addition");
    machine.replaceTournaments([member(5366, "Stockholmsmästerskapet")]);
    assert.equal(machine.state.status, "pending_addition");
    assert.deepEqual(selectedIds(machine), [5366]);
    assert.equal(machine.addVerifiedRilton(null), true);

    await machine.verifyRiltonUrl("https://chess-results.com/tnr967028.aspx");
    assert.equal(machine.state.status, "failure");
    machine.replaceTournaments([]);
    await machine.verifyRiltonUrl("https://chess-results.com/tnr967028.aspx");
    machine.replaceTournaments([rilton(967028, "Rilton U1800 2024/2025")]);
    assert.equal(machine.state.status, "idle");
    assert.equal(machine.addVerifiedRilton(null), false);
}

process.stdout.write("tournament search browser state tests passed\n");
