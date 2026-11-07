import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

async function moduleUrl(relativePath, replacements = new Map()) {
    let source = await readFile(new URL(relativePath, import.meta.url), "utf8");
    for (const [specifier, replacement] of replacements) {
        source = source.replace(specifier, replacement);
    }
    return `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
}

const stateModuleUrl = await moduleUrl(
    "../../senior_gp/web/static/js/tournament-search-state.js",
);
const {
    configurationTournamentConsumer,
    TournamentPicker,
} = await import(await moduleUrl(
    "../../senior_gp/web/static/js/tournament-picker.js",
    new Map([['"./tournament-search-state.js"', JSON.stringify(stateModuleUrl)]]),
));

function lookup(tournamentId) {
    return Promise.resolve({
        tournament: {
            tournament_id: tournamentId,
            name: `Tournament ${tournamentId}`,
            start_date: "2025-09-06",
            end_date: "2025-09-07",
            suggested_scoring: "GP",
        },
    });
}

const stored = {
    source: "member",
    tournament_id: 200,
    name: "Stockholmsmästerskapet",
    scoring: "DM",
    suggested_scoring: "DM",
    rating_floor: null,
    start_date: "2025-03-03",
};
const section = {
    source: "rilton",
    tournament_id: 200,
    name: "Rilton U2200",
    scoring: "GP",
    suggested_scoring: "GP",
    rating_floor: 1800,
    start_date: "2025-03-03",
};
const changes = [];
const commits = [];
const picker = new TournamentPicker({
    lookup,
    verifyRilton() {
        return Promise.resolve({
            tournament: {
                source: "rilton",
                tournament_id: 400,
                name: "Rilton Cup",
                url: "https://chess-results.com/tnr400.aspx?lan=1",
                start_date: null,
                end_date: null,
                edition: "2025/2026",
            },
        });
    },
    consumer: configurationTournamentConsumer({
        initialTournaments: [stored, section],
        selectionChanged(value) {
            changes.push(value.tournaments.map(
                (tournament) => [
                    tournament.tournament_id,
                    tournament.scoring,
                    tournament.rating_floor,
                ],
            ));
        },
        commit(value) {
            commits.push([...value.tournamentKeys]);
            return value;
        },
    }),
});

// Each addition is a change. The additions share a date after the stored ones, so they follow in the order added.
await picker.verifyTournamentId(300);
await picker.verifyTournamentId(100);
assert.deepEqual(changes, [
    [[200, "DM", null], [200, "GP", 1800], [300, "GP", null]],
    [[200, "DM", null], [200, "GP", 1800], [300, "GP", null], [100, "GP", null]],
]);
assert.deepEqual(
    picker.commit().tournamentKeys,
    ["member:200", "rilton:200", "member:300", "member:100"],
);
assert.deepEqual(commits, [["member:200", "rilton:200", "member:300", "member:100"]]);

// A duplicate verification and a repeated scoring type are not changes.
await picker.verifyTournamentId(300);
assert.equal(picker.setScoring("member:300", "GP"), false);
assert.equal(changes.length, 2);

// A change of scoring type or rating floor is a change even though the tournaments stay the same.
assert.equal(picker.setScoring("member:300", "DM"), true);
assert.deepEqual(changes.at(-1)[2], [300, "DM", null]);
assert.equal(picker.setRatingFloor("rilton:200", null), true);
assert.deepEqual(changes.at(-1)[1], [200, "GP", null]);
assert.equal(changes.length, 4);

// New suggestions alone are not a change.
picker.updateSuggestions([{ ...stored, suggested_scoring: "GP" }]);
assert.equal(changes.length, 4);
assert.equal(picker.state.selectedTournaments[0].suggested_scoring, "GP");

// A verified Rilton tournament is a change only once it is added.
await picker.verifyRiltonUrl("https://chess-results.com/tnr400.aspx");
assert.equal(changes.length, 4);
assert.equal(picker.addVerifiedRilton(1900), true);
assert.deepEqual(changes.at(-1).at(-1), [400, "GP", 1900]);
assert.equal(changes.length, 5);

// Restoring the saved tournaments restores their scoring types and floors.
picker.replaceTournaments([stored, section]);
assert.deepEqual(changes.at(-1), [[200, "DM", null], [200, "GP", 1800]]);
assert.deepEqual(picker.value.tournaments, [stored, section]);

assert.equal(picker.removeAllTournaments(), true);
assert.deepEqual(changes.at(-1), []);
assert.equal(picker.removeAllTournaments(), false);
assert.equal(changes.length, 7);

assert.throws(() => configurationTournamentConsumer({
    initialTournaments: null,
    selectionChanged() {},
    commit() {},
}), TypeError);

process.stdout.write("tournament picker consumer tests passed\n");
