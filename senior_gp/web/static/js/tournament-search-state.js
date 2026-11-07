export const MINIMUM_TOURNAMENT_SEARCH_LENGTH = 3;
export const TOURNAMENT_SEARCH_DEBOUNCE_MS = 300;
export const TOURNAMENT_ID_URL_TOKEN = "__tournament_id__";
export const SCORING_TYPES = Object.freeze(["GP", "DM"]);
export const MEMBER_SYSTEM = "member";
export const RILTON = "rilton";

// Member-system and chess-results IDs can be equal, so the source is part of a tournament's identity.
export function tournamentKey(tournament) {
    return `${tournament.source}:${tournament.tournament_id}`;
}

// Order tournaments by date of play, as the server saves them: undated ones
// last, and equal dates in their existing order.
export function byDateOfPlay(tournaments) {
    return [...tournaments].sort(function compareStartDates(first, second) {
        if (first.start_date === second.start_date) {
            return 0;
        }
        if (first.start_date === null) {
            return 1;
        }
        if (second.start_date === null) {
            return -1;
        }
        return first.start_date < second.start_date ? -1 : 1;
    });
}

// A rating floor is a positive Elo below which a player is penalized, or null for no floor.
export function validRatingFloor(value) {
    return value === null || validPositiveInteger(value);
}

function scheduleWithGlobalTimer(callback, delay) {
    return globalThis.setTimeout(callback, delay);
}

function cancelGlobalTimer(timer) {
    globalThis.clearTimeout(timer);
}

export function tournamentSearchUrl(query, endpoint) {
    return `${endpoint}?q=${encodeURIComponent(query)}`;
}

export function tournamentLookupUrl(tournamentId, endpointTemplate) {
    return endpointTemplate.replace(
        TOURNAMENT_ID_URL_TOKEN,
        encodeURIComponent(tournamentId),
    );
}

export function tournamentSearchPresentation(state) {
    switch (state.status) {
        case "idle":
            return {
                messageKey: state.query.length === 0
                    ? "tournament_search.idle"
                    : "tournament_search.minimum",
                parameters: {},
                tone: "quiet",
            };
        case "loading":
            return {
                messageKey: "tournament_search.loading",
                parameters: {},
                tone: "quiet",
            };
        case "empty":
            return {
                messageKey: "tournament_search.empty",
                parameters: {},
                tone: "empty",
            };
        case "failure":
            return {
                messageKey: state.errorMessageKey,
                parameters: {},
                tone: "failure",
            };
        case "results":
            return {
                messageKey: "tournament_search.results",
                parameters: { count: state.tournaments.length },
                tone: "quiet",
            };
        default:
            throw new Error(`Unknown tournament search state: ${state.status}`);
    }
}

function validPositiveInteger(value) {
    return Number.isSafeInteger(value) && value > 0;
}

function validName(value) {
    return typeof value === "string" && value.trim().length > 0;
}

function canonicalDate(value) {
    if (
        typeof value !== "string"
        || !/^\d{4}-\d{2}-\d{2}$/.test(value)
    ) {
        throw new Error("Invalid canonical tournament date");
    }

    const parsed = new Date(`${value}T00:00:00Z`);
    if (
        Number.isNaN(parsed.getTime())
        || parsed.toISOString().slice(0, 10) !== value
    ) {
        throw new Error("Invalid canonical tournament date");
    }
    return value;
}

function canonicalTournament(tournament, expectedTournamentId) {
    if (
        !tournament
        || !validPositiveInteger(tournament.tournament_id)
        || tournament.tournament_id !== expectedTournamentId
        || !validName(tournament.name)
        || !SCORING_TYPES.includes(tournament.suggested_scoring)
    ) {
        throw new Error("Invalid canonical tournament");
    }

    const startDate = canonicalDate(tournament.start_date);
    const endDate = canonicalDate(tournament.end_date);
    if (endDate < startDate) {
        throw new Error("Invalid canonical tournament date range");
    }

    return {
        tournament_id: tournament.tournament_id,
        name: tournament.name,
        start_date: startDate,
        end_date: endDate,
        suggested_scoring: tournament.suggested_scoring,
    };
}

// A verified chess-results tournament. Its page shows both dates or neither.
function canonicalRiltonTournament(tournament) {
    if (
        tournament?.source !== RILTON
        || !validPositiveInteger(tournament.tournament_id)
        || !validName(tournament.name)
        || typeof tournament.url !== "string"
        || typeof tournament.edition !== "string"
        || (tournament.start_date === null) !== (tournament.end_date === null)
    ) {
        throw new Error("Invalid verified Rilton tournament");
    }

    let startDate = null;
    let endDate = null;
    if (tournament.start_date !== null) {
        startDate = canonicalDate(tournament.start_date);
        endDate = canonicalDate(tournament.end_date);
        if (endDate < startDate) {
            throw new Error("Invalid Rilton tournament date range");
        }
    }

    return {
        source: RILTON,
        tournament_id: tournament.tournament_id,
        name: tournament.name,
        url: tournament.url,
        start_date: startDate,
        end_date: endDate,
        edition: tournament.edition,
    };
}

function selectedTournament(tournament) {
    const rilton = tournament?.source === RILTON;
    if (
        ![MEMBER_SYSTEM, RILTON].includes(tournament?.source)
        || !validPositiveInteger(tournament.tournament_id)
        || !validName(tournament.name)
        || !SCORING_TYPES.includes(tournament.scoring)
        || !SCORING_TYPES.includes(tournament.suggested_scoring)
        || (rilton && tournament.scoring !== "GP")
        || (rilton && !validRatingFloor(tournament.rating_floor))
        || (tournament.start_date !== null && canonicalDate(tournament.start_date) !== tournament.start_date)
    ) {
        throw new Error("Invalid selected tournament");
    }
    return {
        source: tournament.source,
        tournament_id: tournament.tournament_id,
        name: tournament.name,
        scoring: tournament.scoring,
        suggested_scoring: tournament.suggested_scoring,
        rating_floor: rilton ? tournament.rating_floor : null,
        start_date: tournament.start_date,
    };
}

export class TournamentSearchState {
    constructor({
        search,
        onChange = () => {},
        schedule = scheduleWithGlobalTimer,
        cancel = cancelGlobalTimer,
        debounceMs = TOURNAMENT_SEARCH_DEBOUNCE_MS,
    }) {
        this.search = search;
        this.onChange = onChange;
        this.schedule = schedule;
        this.cancel = cancel;
        this.debounceMs = debounceMs;
        this.timer = null;
        this.requestVersion = 0;
        this.state = {
            status: "idle",
            searchText: "",
            query: "",
            tournaments: [],
            errorMessageKey: null,
            problems: [],
        };
    }

    setSearchText(searchText) {
        const query = searchText.trim();
        this.requestVersion += 1;
        const requestVersion = this.requestVersion;
        this.#cancelPendingSearch();

        if (query.length < MINIMUM_TOURNAMENT_SEARCH_LENGTH) {
            this.#transition("idle", searchText, query);
            return;
        }

        this.#transition(
            "loading",
            searchText,
            query,
            this.state.tournaments,
        );
        this.timer = this.schedule(() => {
            this.timer = null;
            this.#performSearch(query, searchText, requestVersion);
        }, this.debounceMs);
    }

    clear() {
        this.setSearchText("");
    }

    dispose() {
        this.requestVersion += 1;
        this.#cancelPendingSearch();
    }

    #cancelPendingSearch() {
        if (this.timer !== null) {
            this.cancel(this.timer);
            this.timer = null;
        }
    }

    #transition(
        status,
        searchText,
        query,
        tournaments = [],
        errorMessageKey = null,
        problems = [],
    ) {
        this.state = {
            status,
            searchText,
            query,
            tournaments,
            errorMessageKey,
            problems,
        };
        this.onChange(this.state);
    }

    async #performSearch(query, searchText, requestVersion) {
        try {
            const response = await this.search(query);
            if (requestVersion !== this.requestVersion) {
                return;
            }

            const tournaments = response.tournaments ?? [];
            this.#transition(
                tournaments.length > 0 ? "results" : "empty",
                searchText,
                query,
                tournaments,
            );
        } catch (error) {
            if (requestVersion !== this.requestVersion) {
                return;
            }
            this.#transition(
                "failure",
                searchText,
                query,
                [],
                error?.messageKey ?? "errors.member_system.unavailable",
                error?.problems ?? [],
            );
        }
    }
}

/**
 * The selected tournaments in order of date of play, keyed by `tournamentKey`.
 *
 * A verified member-system tournament takes its place by date with its
 * suggested scoring type. A verified Rilton tournament waits in the `pending_addition`
 * status until `addVerifiedRilton` adds it with the operator's rating floor.
 * Only `setScoring`, `setRatingFloor`, and `replaceTournaments` after a failed
 * save change the operator's choices for a selected tournament.
 */
export class TournamentSelectionState {
    constructor({
        lookup,
        verifyRilton,
        onChange = () => {},
        initialTournaments = [],
    }) {
        this.lookup = lookup;
        this.verifyRilton = verifyRilton;
        this.onChange = onChange;
        this.requestVersion = 0;
        this.state = {
            status: "idle",
            verifiedTournament: null,
            selectedTournaments: initialTournaments.map(selectedTournament),
            errorMessageKey: null,
            problems: [],
        };
    }

    selectSearchResult(searchResult) {
        return this.verifyTournamentId(searchResult?.tournament_id);
    }

    async verifyTournamentId(value) {
        this.requestVersion += 1;
        const requestVersion = this.requestVersion;
        const tournamentId = Number(value);

        if (
            !validPositiveInteger(tournamentId)
            || String(tournamentId) !== String(value).trim()
        ) {
            this.#transition(
                "failure",
                null,
                "errors.tournament_lookup.invalid_input",
            );
            return;
        }

        this.#transition("verifying");
        try {
            const response = await this.lookup(tournamentId);
            if (requestVersion !== this.requestVersion) {
                return;
            }
            const tournament = canonicalTournament(
                response?.tournament,
                tournamentId,
            );
            const key = tournamentKey({ source: MEMBER_SYSTEM, ...tournament });
            if (
                this.state.selectedTournaments.some(
                    (selected) => tournamentKey(selected) === key,
                )
            ) {
                this.#transition(
                    "failure",
                    null,
                    "errors.tournament_selection.duplicate",
                );
                return;
            }

            this.#transition("verified", tournament, null, byDateOfPlay([
                ...this.state.selectedTournaments,
                {
                    source: MEMBER_SYSTEM,
                    tournament_id: tournament.tournament_id,
                    name: tournament.name,
                    scoring: tournament.suggested_scoring,
                    suggested_scoring: tournament.suggested_scoring,
                    rating_floor: null,
                    start_date: tournament.start_date,
                },
            ]));
        } catch (error) {
            if (requestVersion !== this.requestVersion) {
                return;
            }
            this.#transition(
                "failure",
                null,
                error?.messageKey ?? "errors.member_system.unavailable",
                this.state.selectedTournaments,
                error?.problems ?? [],
            );
        }
    }

    async verifyRiltonUrl(value) {
        this.requestVersion += 1;
        const requestVersion = this.requestVersion;
        const url = String(value ?? "").trim();
        if (url === "") {
            this.#transition("failure", null, "errors.rilton.invalid_url");
            return;
        }

        this.#transition("verifying");
        try {
            const response = await this.verifyRilton(url);
            if (requestVersion !== this.requestVersion) {
                return;
            }
            const tournament = canonicalRiltonTournament(response?.tournament);
            if (this.#find(tournamentKey(tournament)) !== undefined) {
                this.#transition(
                    "failure",
                    null,
                    "errors.tournament_selection.duplicate",
                );
                return;
            }
            this.#transition("pending_addition", tournament);
        } catch (error) {
            if (requestVersion !== this.requestVersion) {
                return;
            }
            this.#transition(
                "failure",
                null,
                error?.messageKey ?? "errors.rilton.unavailable",
                this.state.selectedTournaments,
                error?.problems ?? [],
            );
        }
    }

    /**
     * Add the pending Rilton tournament with `ratingFloor` and return true.
     * Return false when nothing is pending.
     */
    addVerifiedRilton(ratingFloor) {
        if (!validRatingFloor(ratingFloor)) {
            throw new Error(`Invalid rating floor: ${ratingFloor}`);
        }
        const tournament = this.state.verifiedTournament;
        if (this.state.status !== "pending_addition") {
            return false;
        }

        this.requestVersion += 1;
        this.#transition("idle", null, null, byDateOfPlay([
            ...this.state.selectedTournaments,
            {
                source: RILTON,
                tournament_id: tournament.tournament_id,
                name: tournament.name,
                scoring: "GP",
                suggested_scoring: "GP",
                rating_floor: ratingFloor,
                start_date: tournament.start_date,
            },
        ]));
        return true;
    }

    clear() {
        this.requestVersion += 1;
        this.#transition("idle");
    }

    setScoring(key, scoring) {
        if (!SCORING_TYPES.includes(scoring)) {
            throw new Error(`Unknown scoring type: ${scoring}`);
        }
        const current = this.#find(key);
        if (
            current === undefined
            || current.source === RILTON
            || current.scoring === scoring
        ) {
            return false;
        }
        this.#change(current, { scoring });
        return true;
    }

    setRatingFloor(key, ratingFloor) {
        if (!validRatingFloor(ratingFloor)) {
            throw new Error(`Invalid rating floor: ${ratingFloor}`);
        }
        const current = this.#find(key);
        if (
            current === undefined
            || current.source !== RILTON
            || current.rating_floor === ratingFloor
        ) {
            return false;
        }
        this.#change(current, { rating_floor: ratingFloor });
        return true;
    }

    /**
     * Take the suggestions and start dates from a successful save, and order
     * the list by date again, without changing the operator's choices or
     * abandoning a pending verification. A save can find the date of a
     * tournament stored without one.
     */
    updateSuggestions(savedTournaments) {
        const saved = new Map(
            savedTournaments.map((tournament) => [tournamentKey(tournament), tournament]),
        );
        this.#transition(
            this.state.status,
            this.state.verifiedTournament,
            this.state.errorMessageKey,
            byDateOfPlay(this.state.selectedTournaments.map(function withSavedSuggestions(tournament) {
                const match = saved.get(tournamentKey(tournament));
                return match === undefined
                    ? tournament
                    : {
                        ...tournament,
                        suggested_scoring: match.suggested_scoring,
                        start_date: match.start_date,
                    };
            })),
            this.state.problems,
        );
    }

    removeTournament(key) {
        const remaining = this.state.selectedTournaments.filter(
            (tournament) => tournamentKey(tournament) !== key,
        );
        if (remaining.length === this.state.selectedTournaments.length) {
            return false;
        }

        this.replaceTournaments(remaining);
        return true;
    }

    removeAllTournaments() {
        if (this.state.selectedTournaments.length === 0) {
            return false;
        }

        this.replaceTournaments([]);
        return true;
    }

    /**
     * Replace the list after an edit or a failed save. Keep a verification in
     * progress. Keep a verified Rilton tournament waiting to be added, unless
     * the new list already has it.
     */
    replaceTournaments(tournaments) {
        const { status, verifiedTournament } = this.state;
        const keep = status === "verifying" || (
            status === "pending_addition"
            && !tournaments.some(
                (tournament) => tournamentKey(tournament) === tournamentKey(verifiedTournament),
            )
        );
        if (keep) {
            this.#transition(status, verifiedTournament, null, tournaments);
            return;
        }
        this.requestVersion += 1;
        this.#transition("idle", null, null, tournaments);
    }

    #find(key) {
        return this.state.selectedTournaments.find(
            (tournament) => tournamentKey(tournament) === key,
        );
    }

    #change(current, changes) {
        this.replaceTournaments(
            this.state.selectedTournaments.map(
                (tournament) => (
                    tournament === current
                        ? { ...tournament, ...changes }
                        : tournament
                ),
            ),
        );
    }

    dispose() {
        this.requestVersion += 1;
    }

    #transition(
        status,
        verifiedTournament = null,
        errorMessageKey = null,
        selectedTournaments = this.state.selectedTournaments,
        problems = [],
    ) {
        this.state = {
            status,
            verifiedTournament,
            selectedTournaments,
            errorMessageKey,
            problems,
        };
        this.onChange(this.state);
    }
}
