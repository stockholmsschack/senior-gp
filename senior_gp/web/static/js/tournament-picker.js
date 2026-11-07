import {
    tournamentKey,
    TournamentSelectionState,
} from "./tournament-search-state.js";

function selectionValue(tournaments) {
    const selectedTournaments = Object.freeze([...tournaments]);
    return Object.freeze({
        tournaments: selectedTournaments,
        tournamentKeys: Object.freeze(selectedTournaments.map(tournamentKey)),
    });
}

// The signature includes each scoring type and rating floor, so a change of
// either counts as a change of selection even when the tournaments stay the
// same. Suggestions, dates and order are not part of it: the server orders the
// list by date, so a reorder or a new suggestion from a save causes no save.
function selectionSignature(value) {
    return JSON.stringify(
        value.tournaments.map(
            (tournament) => [
                tournamentKey(tournament),
                tournament.scoring,
                tournament.rating_floor,
            ],
        ).sort(),
    );
}

export function configurationTournamentConsumer({
    initialTournaments,
    selectionChanged,
    commit,
}) {
    if (!Array.isArray(initialTournaments)) {
        throw new TypeError("Picker initial tournaments must be an array");
    }
    if (
        typeof selectionChanged !== "function"
        || typeof commit !== "function"
    ) {
        throw new TypeError("Picker consumer callbacks are required");
    }
    return {
        initialTournaments,
        selectionChanged,
        commit,
    };
}

export class TournamentPicker {
    constructor({
        lookup,
        verifyRilton,
        consumer,
        onChange = () => {},
    }) {
        this.consumer = consumer;
        this.onChange = onChange;
        this.selectionState = new TournamentSelectionState({
            lookup,
            verifyRilton,
            initialTournaments: consumer.initialTournaments,
            onChange: this.#selectionChanged.bind(this),
        });
        this.value = selectionValue(
            this.selectionState.state.selectedTournaments,
        );
        this.valueSignature = selectionSignature(this.value);
    }

    selectSearchResult(searchResult) {
        return this.selectionState.selectSearchResult(searchResult);
    }

    verifyTournamentId(value) {
        return this.selectionState.verifyTournamentId(value);
    }

    verifyRiltonUrl(value) {
        return this.selectionState.verifyRiltonUrl(value);
    }

    addVerifiedRilton(ratingFloor) {
        return this.selectionState.addVerifiedRilton(ratingFloor);
    }

    clearStatus() {
        this.selectionState.clear();
    }

    setScoring(key, scoring) {
        return this.selectionState.setScoring(key, scoring);
    }

    setRatingFloor(key, ratingFloor) {
        return this.selectionState.setRatingFloor(key, ratingFloor);
    }

    updateSuggestions(savedTournaments) {
        this.selectionState.updateSuggestions(savedTournaments);
    }

    removeTournament(key) {
        return this.selectionState.removeTournament(key);
    }

    removeAllTournaments() {
        return this.selectionState.removeAllTournaments();
    }

    replaceTournaments(tournaments) {
        this.selectionState.replaceTournaments(tournaments);
    }

    commit() {
        return this.consumer.commit(this.value);
    }

    dispose() {
        this.selectionState.dispose();
    }

    get state() {
        return this.selectionState.state;
    }

    #selectionChanged(state) {
        const value = selectionValue(state.selectedTournaments);
        const nextSignature = selectionSignature(value);
        this.value = value;
        if (nextSignature !== this.valueSignature) {
            this.valueSignature = nextSignature;
            this.consumer.selectionChanged(value);
        }
        this.onChange(state, value);
    }
}
