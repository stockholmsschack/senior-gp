import { ConfigurationSaveQueue } from "./configuration-save-queue.js";
import { html, nothing, render } from "./lit-html.js";
import { translate } from "./locale.js";
import { problemList } from "./problem-list.js";
import {
    configurationTournamentConsumer,
    TournamentPicker,
} from "./tournament-picker.js";
import {
    RILTON,
    SCORING_TYPES,
    tournamentKey,
    tournamentLookupUrl,
    tournamentSearchPresentation,
    TournamentSearchState,
    tournamentSearchUrl,
} from "./tournament-search-state.js";

function renderStatus(statusElement, state) {
    const presentation = tournamentSearchPresentation(state);
    let className = "tournament-search-status";
    if (presentation.tone === "failure") {
        className += " alert alert-danger py-2";
    } else if (presentation.tone === "empty") {
        className += " alert alert-secondary py-2";
    } else {
        className += " form-text";
    }

    statusElement.className = className;
    statusElement.dataset.searchState = state.status;
    render(
        html`
            ${state.status === "loading"
                ? html`
                    <span
                        class="spinner-border spinner-border-sm me-2"
                        aria-hidden="true"
                    ></span>
                `
                : nothing}
            ${state.problems?.length ? "" : translate(presentation.messageKey, presentation.parameters)}
            ${problemList(state.problems)}
        `,
        statusElement,
    );
}

function renderResults(resultsElement, tournaments, selectTournament) {
    render(
        html`
            ${tournaments.map(function tournamentResult(tournament) {
                const groupNames = tournament.matching_groups
                    .map((group) => group.name)
                    .join(", ");
                return html`
                    <li class="list-group-item">
                        <div class="fw-semibold">
                            ${tournament.name}
                            <span class="badge text-bg-secondary ms-2">
                                #${tournament.tournament_id}
                            </span>
                        </div>
                        <div class="small text-body-secondary">
                            ${translate("tournament_search.matching_groups", {
                                groups: groupNames,
                            })}
                        </div>
                        <button
                            class="btn btn-outline-primary btn-sm mt-2"
                            type="button"
                            @click=${function handleTournamentSelection() {
                                selectTournament(tournament);
                            }}
                        >
                            ${translate("tournament_search.select")}
                        </button>
                    </li>
                `;
            })}
        `,
        resultsElement,
    );
}

// Return the floor typed in a rating-floor box: null for an empty box, a
// positive whole number, or undefined when the text is neither.
function typedRatingFloor(text) {
    const trimmed = text.trim();
    if (trimmed === "") {
        return null;
    }
    return /^[1-9][0-9]*$/.test(trimmed) ? Number(trimmed) : undefined;
}

function tournamentLink(tournament) {
    return tournament.source === RILTON
        ? `https://chess-results.com/tnr${tournament.tournament_id}.aspx?lan=1`
        : `https://member.schack.se/ShowAllTournamentRegistrationsServlet?id=${tournament.tournament_id}`;
}

function scoringControl(tournament, changeScoring) {
    if (tournament.source === RILTON) {
        return html`<span class="badge bg-body-tertiary text-body border">${tournament.scoring}</span>`;
    }
    return html`
        <select
            class="form-select form-select-sm w-auto"
            aria-label=${translate(
                "tournament_selection.scoring_label",
                { name: tournament.name },
            )}
            data-scoring-select
            data-scoring=${tournament.scoring}
            @change=${function handleScoringChange(event) {
                changeScoring(tournament, event.target.value);
            }}
        >
            ${SCORING_TYPES.map((scoring) => html`
                <option value=${scoring}>${scoring}</option>
            `)}
        </select>
    `;
}

// A box for the Elo below which the section's players are penalized. An empty
// box means no floor. `changeRatingFloor` receives each committed value, or
// undefined when the text is not a floor. From the first keystroke until the
// operator commits a floor, the box is marked `data-editing`, so a render does
// not overwrite the text.
function ratingFloorControl(tournament, changeRatingFloor) {
    if (tournament.source !== RILTON) {
        return nothing;
    }
    return html`
        <div class="input-group input-group-sm has-validation" style="width: 15rem">
            <span class="input-group-text">
                ${translate("tournament_selection.rating_floor_prefix")}
            </span>
            <input
                class="form-control"
                type="text"
                inputmode="numeric"
                placeholder=${translate("tournament_selection.rating_floor_none")}
                aria-label=${translate(
                    "tournament_selection.rating_floor_label",
                    { name: tournament.name },
                )}
                data-rating-floor-input
                data-rating-floor=${tournament.rating_floor ?? ""}
                @input=${function handleRatingFloorInput(event) {
                    event.target.dataset.editing = "true";
                    event.target.classList.toggle(
                        "is-invalid",
                        typedRatingFloor(event.target.value) === undefined,
                    );
                }}
                @change=${function handleRatingFloorChange(event) {
                    const ratingFloor = typedRatingFloor(event.target.value);
                    if (ratingFloor !== undefined) {
                        delete event.target.dataset.editing;
                    }
                    changeRatingFloor(tournament, ratingFloor);
                }}
            >
            <div class="invalid-feedback">
                ${translate("tournament_selection.rating_floor_invalid")}
            </div>
        </div>
    `;
}

// Show each rating floor box's stored floor, except in a box being edited.
// As with the selects, set the value here instead of through a binding.
function showRatingFloors(element) {
    for (const input of element.querySelectorAll("[data-rating-floor-input]")) {
        if (input.dataset.editing === undefined) {
            input.value = input.dataset.ratingFloor;
            input.classList.remove("is-invalid");
        }
    }
}

function renderSelectedTournaments(
    selectedElement,
    tournaments,
    requestTournamentRemoval,
    changeScoring,
    changeRatingFloor,
) {
    selectedElement.dataset.selectedCount = String(tournaments.length);
    render(
        tournaments.length === 0
            ? html`
                <p class="text-body-secondary mb-0">
                    ${translate("tournaments.none")}
                </p>
            `
            : html`
                <ul class="list-group">
                    ${tournaments.map((tournament) => html`
                        <li
                            class="list-group-item d-flex flex-wrap gap-3 align-items-center"
                            data-selected-tournament-key=${tournamentKey(tournament)}
                        >
                            <div class="fw-semibold flex-grow-1">
                                <a
                                    class="link-body-emphasis link-underline-opacity-25 link-underline-opacity-75-hover"
                                    href=${tournamentLink(tournament)}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                >
                                    ${tournament.name}
                                    (${tournament.tournament_id})
                                </a>
                                <div class="small fw-normal text-body-secondary">
                                    ${tournament.start_date
                                        ?? translate("tournament_selection.no_start_date")}
                                </div>
                                ${tournament.scoring === tournament.suggested_scoring
                                    ? nothing
                                    : html`
                                        <div class="form-text">
                                            ${translate(
                                                "tournament_selection.scoring_differs",
                                                { scoring: tournament.suggested_scoring },
                                            )}
                                        </div>
                                    `}
                            </div>
                            ${scoringControl(tournament, changeScoring)}
                            ${ratingFloorControl(tournament, changeRatingFloor)}
                            <button
                                class="btn btn-outline-danger btn-sm"
                                type="button"
                                aria-label=${translate(
                                    "tournament_selection.remove_label",
                                    { name: tournament.name },
                                )}
                                @click=${function handleRemoval() {
                                    requestTournamentRemoval(tournament);
                                }}
                            >
                                ${translate("tournament_selection.remove")}
                            </button>
                        </li>
                    `)}
                </ul>
            `,
        selectedElement,
    );
    // Set each select's value here instead of through a `.value` binding.
    // lit-html sets a bound property only when it differs from the last
    // render, and a failed save can restore a value that equals the last
    // rendered one while the select still shows the operator's choice.
    for (const select of selectedElement.querySelectorAll("[data-scoring-select]")) {
        select.value = select.dataset.scoring;
    }
    showRatingFloors(selectedElement);
}

// Name an entry with its source and ID, because the two sources can share an ID.
function entryLabel(tournament) {
    return `${translate(`source.${tournament.source}`)}: ${tournament.name} (${tournament.tournament_id})`;
}

function renderRemovalEntries(element, tournaments) {
    render(
        html`
            <ul class="mb-0">
                ${tournaments.map((tournament) => html`<li>${entryLabel(tournament)}</li>`)}
            </ul>
        `,
        element,
    );
}

function riltonDates(tournament) {
    if (tournament.start_date === null) {
        return translate("rilton.no_dates");
    }
    if (tournament.start_date === tournament.end_date) {
        return tournament.start_date;
    }
    return translate("rilton.dates", {
        start: tournament.start_date,
        end: tournament.end_date,
    });
}

// The verified Rilton tournament with its rating floor box and an Add button
// that stays disabled while the committed text is not a floor. `ratingFloor`
// is then undefined.
function renderPendingRilton(element, state, ratingFloor, handlers) {
    if (state.status !== "pending_addition") {
        render(nothing, element);
        return;
    }
    const tournament = { ...state.verifiedTournament, rating_floor: ratingFloor ?? null };
    render(
        html`
            <div class="card mt-3" data-rilton-pending-tournament>
                <div class="card-body d-flex flex-wrap gap-3 align-items-center">
                    <div class="flex-grow-1">
                        <a
                            class="fw-semibold link-body-emphasis"
                            href=${tournament.url}
                            target="_blank"
                            rel="noopener noreferrer"
                        >
                            ${tournament.name} (${tournament.tournament_id})
                        </a>
                        <div class="small text-body-secondary">
                            ${riltonDates(tournament)}
                            ·
                            ${translate("rilton.edition", { edition: tournament.edition })}
                        </div>
                    </div>
                    ${ratingFloorControl(tournament, handlers.changeRatingFloor)}
                    <button
                        class="btn btn-primary btn-sm"
                        type="button"
                        ?disabled=${ratingFloor === undefined}
                        data-add-rilton
                        @click=${handlers.add}
                    >
                        ${translate("rilton.add")}
                    </button>
                    <button
                        class="btn btn-outline-secondary btn-sm"
                        type="button"
                        @click=${handlers.discard}
                    >
                        ${translate("tournament_selection.cancel")}
                    </button>
                </div>
            </div>
        `,
        element,
    );
    showRatingFloors(element);
}

function renderVerificationStatus(selectionElement, state) {
    selectionElement.dataset.selectionState = state.status;

    if (state.status === "failure" && state.problems?.length) {
        selectionElement.className = "alert alert-danger mt-3";
        selectionElement.setAttribute("role", "alert");
        render(problemList(state.problems), selectionElement);
        return;
    }
    selectionElement.setAttribute("role", "status");
    if (state.status !== "verifying") {
        selectionElement.className = "";
        render(nothing, selectionElement);
        return;
    }

    selectionElement.className = "alert alert-secondary mt-3";
    render(
        html`
            <span
                class="spinner-border spinner-border-sm me-2"
                aria-hidden="true"
            ></span>
            ${translate("tournament_selection.verifying")}
        `,
        selectionElement,
    );
}

function showSelectionToast(
    toastElement,
    messageElement,
    toast,
    state,
) {
    if (state.status !== "failure") {
        return;
    }

    toastElement.className = "toast border-0 text-bg-danger";
    toastElement.setAttribute("role", "alert");
    toastElement.setAttribute("aria-live", "assertive");
    const message = state.problems?.length
        ? ""
        : translate(state.errorMessageKey);
    render(html`${message}${problemList(state.problems)}`, messageElement);
    toast.show();
}

async function requestJson(url, options, failure, fallbackMessageKey) {
    const response = await fetch(url, {
        ...options,
        headers: { Accept: "application/json", ...options.headers },
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error(failure);
        error.code = payload.error?.code;
        error.details = payload.error?.details ?? {};
        error.messageKey = payload.error?.message_key ?? fallbackMessageKey;
        error.problems = payload.error?.details?.problems ?? [];
        throw error;
    }
    return payload.data;
}

function searchTournaments(endpoint, query) {
    return requestJson(
        tournamentSearchUrl(query, endpoint),
        {},
        "Tournament search failed",
        "errors.member_system.unavailable",
    );
}

function lookupTournament(endpointTemplate, tournamentId) {
    return requestJson(
        tournamentLookupUrl(tournamentId, endpointTemplate),
        {},
        "Tournament lookup failed",
        "errors.member_system.unavailable",
    );
}

function verifyRiltonUrl(endpoint, url) {
    return requestJson(
        endpoint,
        {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ url }),
        },
        "Rilton verification failed",
        "errors.rilton.unavailable",
    );
}

function saveTournaments(endpoint, revision, tournaments) {
    return requestJson(
        endpoint,
        {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                revision,
                tournaments: tournaments.map((tournament) => ({
                    source: tournament.source,
                    tournament_id: tournament.tournament_id,
                    scoring: tournament.scoring,
                    rating_floor: tournament.rating_floor,
                })),
            }),
        },
        "Tournament configuration save failed",
        "errors.internal",
    );
}

// Show the saved configuration in the page summary.
function renderSummary(summary, saved) {
    if (!summary) {
        return;
    }
    const rilton = saved.tournaments.filter(
        (tournament) => tournament.source === RILTON,
    ).length;
    summary.querySelector("[data-configuration-intro]").hidden = false;
    summary.querySelector("[data-configuration-none]").hidden = true;
    summary.querySelector("[data-configuration-count-display]").textContent =
        translate("home.tournament_count", {
            member: saved.tournaments.length - rilton,
            rilton,
        });
    summary.querySelector("[data-configuration-revision-display]").textContent =
        String(saved.revision);
}

function renderSaveStatus(element, state) {
    element.dataset.saveState = state.status;
    if (state.status === "idle") {
        element.className = "mt-3";
        render(nothing, element);
        return;
    }
    if (state.status === "saving") {
        element.className = "alert alert-secondary mt-3";
        render(
            html`
                <span
                    class="spinner-border spinner-border-sm me-2"
                    aria-hidden="true"
                ></span>
                ${translate("tournament_selection.saving")}
            `,
            element,
        );
        return;
    }
    element.className = state.status === "saved"
        ? "alert alert-success mt-3"
        : "alert alert-danger mt-3";
    const messageKey = state.status === "saved"
        ? "tournament_selection.saved"
        : state.messageKey;
    render(html`
        ${state.entry ? `${entryLabel(state.entry)}: ` : ""}
        ${state.problems?.length ? "" : translate(messageKey)}
        ${problemList(state.problems)}
        ${state.reloadUrl
            ? html`
                <div class="mt-2">
                    <a class="btn btn-outline-danger btn-sm" href=${state.reloadUrl} data-reload-configuration>
                        ${translate("tournament_selection.reload")}
                    </a>
                </div>
            `
            : nothing}
    `, element);
}

export function mountTournamentSearch(root) {
    const input = root.querySelector("[data-tournament-search-input]");
    const status = root.querySelector("[data-tournament-search-status]");
    const results = root.querySelector("[data-tournament-search-results]");
    const pastedIdForm = root.querySelector("[data-tournament-id-form]");
    const pastedIdInput = root.querySelector("[data-tournament-id-input]");
    const sourceSelect = root.querySelector("[data-tournament-source]");
    const memberAddition = root.querySelector("[data-member-addition]");
    const riltonAddition = root.querySelector("[data-rilton-addition]");
    const riltonUrlForm = root.querySelector("[data-rilton-url-form]");
    const riltonUrlInput = root.querySelector("[data-rilton-url-input]");
    const riltonPending = root.querySelector("[data-rilton-pending]");
    const selected = root.querySelector("[data-selected-tournaments]");
    const removeAllButton = root.querySelector(
        "[data-remove-all-tournaments]",
    );
    const selection = root.querySelector("[data-tournament-selection]");
    const selectionToastElement = root.querySelector(
        "[data-tournament-selection-toast]",
    );
    const selectionToastMessage = root.querySelector(
        "[data-tournament-selection-toast-message]",
    );
    const saveStatus = root.querySelector("[data-tournament-save-status]");
    const summary = document.querySelector("[data-configuration-summary]");
    const removalDialogElement = root.querySelector(
        "[data-tournament-removal-dialog]",
    );
    const removalHeading = root.querySelector(
        "[data-tournament-removal-heading]",
    );
    const removalDescription = root.querySelector(
        "[data-tournament-removal-description]",
    );
    const removalTournamentName = root.querySelector(
        "[data-tournament-removal-name]",
    );
    const confirmRemovalButton = root.querySelector(
        "[data-confirm-tournament-removal]",
    );
    const initialTournaments = JSON.parse(
        document.getElementById("selected-tournaments-data").textContent,
    );
    const searchEndpoint = root.dataset.searchEndpoint;
    const lookupEndpointTemplate = root.dataset.lookupEndpointTemplate;
    const riltonVerifyEndpoint = root.dataset.riltonVerifyEndpoint;
    const saveEndpoint = root.dataset.saveEndpoint;
    const additionArea = root.querySelector("[data-tournament-addition]");
    let replacingFailedSelection = false;
    // Set after a stale save. The list, the addition card, and the removal
    // dialog then take no input.
    let stale = false;
    let pendingRemoval = null;
    // The floor typed for the pending Rilton tournament: null for no floor, or
    // undefined while the box holds something other than a floor.
    let pendingRatingFloor = null;
    const removalDialog = new globalThis.bootstrap.Modal(removalDialogElement);
    const selectionToast = new globalThis.bootstrap.Toast(
        selectionToastElement,
        { delay: 8000 },
    );
    status.textContent = "";
    selection.textContent = "";

    function requestTournamentRemoval(tournament) {
        pendingRemoval = {
            kind: "one",
            key: tournamentKey(tournament),
        };
        removalHeading.textContent = translate(
            "tournament_selection.remove_heading",
        );
        removalDescription.textContent = translate(
            "tournament_selection.remove_confirmation",
        );
        renderRemovalEntries(removalTournamentName, [tournament]);
        confirmRemovalButton.textContent = translate(
            "tournament_selection.remove",
        );
        removalDialog.show();
    }

    function requestAllTournamentsRemoval() {
        const tournaments = picker.state.selectedTournaments;
        if (tournaments.length === 0) {
            return;
        }
        pendingRemoval = { kind: "all" };
        removalHeading.textContent = translate(
            "tournament_selection.remove_all_heading",
        );
        removalDescription.textContent = translate(
            "tournament_selection.remove_all_confirmation",
        );
        renderRemovalEntries(removalTournamentName, tournaments);
        confirmRemovalButton.textContent = translate(
            "tournament_selection.remove_all",
        );
        removalDialog.show();
    }

    function changeScoring(tournament, scoring) {
        picker.setScoring(tournamentKey(tournament), scoring);
    }

    function changeRatingFloor(tournament, ratingFloor) {
        if (ratingFloor !== undefined) {
            picker.setRatingFloor(tournamentKey(tournament), ratingFloor);
        }
    }

    const saveQueue = new ConfigurationSaveQueue({
        revision: Number(root.dataset.configurationRevision),
        savedTournaments: initialTournaments,
        save(revision, tournaments) {
            return saveTournaments(saveEndpoint, revision, tournaments);
        },
        onSaving() {
            renderSaveStatus(saveStatus, { status: "saving" });
        },
        onSaved(saved, latest) {
            root.dataset.configurationRevision = String(saved.revision);
            renderSummary(summary, saved);
            if (latest) {
                picker.updateSuggestions(saved.tournaments);
                renderSaveStatus(saveStatus, { status: "saved" });
            }
        },
        onFailure(error, savedTournaments, isStale) {
            if (isStale) {
                stale = true;
            }
            // A refusal of one entry gives its source and ID. Find it before
            // the saved list replaces it.
            const entry = picker.state.selectedTournaments.find(
                (tournament) => tournament.source === error?.details?.source
                    && tournament.tournament_id === error?.details?.tournament_id,
            );
            replacingFailedSelection = true;
            picker.replaceTournaments(savedTournaments);
            replacingFailedSelection = false;
            // A lookup still in progress would add its tournament and save
            // again at once, replacing this error before the operator reads
            // it. A verified Rilton tournament waits for Add, so it stays.
            if (stale || picker.state.status === "verifying") {
                picker.clearStatus();
            }
            if (stale) {
                pendingRemoval = null;
                removalDialog.hide();
                additionArea.inert = true;
                selected.inert = true;
                renderTournamentSelection(picker.state);
            }
            renderSaveStatus(saveStatus, {
                status: "failure",
                messageKey: error?.messageKey ?? "errors.internal",
                problems: error?.problems ?? [],
                entry,
                reloadUrl: stale ? root.dataset.reloadUrl : null,
            });
        },
    });

    // Tell the generation section the saved revision and tournament count,
    // whether a save is queued or running, and whether a save was refused as
    // stale.
    function announceConfiguration() {
        globalThis.dispatchEvent(new CustomEvent(
            "senior:configuration-state",
            {
                detail: {
                    revision: saveQueue.revision,
                    tournamentCount: saveQueue.savedTournaments.length,
                    saving: saveQueue.busy,
                    stale,
                },
            },
        ));
    }

    function scheduleSave(tournaments) {
        if (!replacingFailedSelection && saveQueue.schedule(tournaments)) {
            announceConfiguration();
            saveQueue.pending.then(announceConfiguration);
        }
    }

    const picker = new TournamentPicker({
        lookup(tournamentId) {
            return lookupTournament(lookupEndpointTemplate, tournamentId);
        },
        verifyRilton(url) {
            return verifyRiltonUrl(riltonVerifyEndpoint, url);
        },
        consumer: configurationTournamentConsumer({
            initialTournaments,
            selectionChanged(value) {
                scheduleSave(value.tournaments);
            },
            commit(value) {
                return value;
            },
        }),
        onChange(nextState) {
            renderTournamentSelection(nextState);
        },
    });
    function renderTournamentSelection(state) {
        removeAllButton.disabled = stale
            || state.selectedTournaments.length === 0;
        renderSelectedTournaments(
            selected,
            state.selectedTournaments,
            requestTournamentRemoval,
            changeScoring,
            changeRatingFloor,
        );
        if (state.status !== "pending_addition") {
            pendingRatingFloor = null;
        }
        renderPendingRilton(riltonPending, state, pendingRatingFloor, {
            changeRatingFloor(_tournament, ratingFloor) {
                pendingRatingFloor = ratingFloor;
                renderTournamentSelection(picker.state);
            },
            add() {
                if (picker.addVerifiedRilton(pendingRatingFloor)) {
                    riltonUrlInput.value = "";
                }
            },
            discard() {
                picker.clearStatus();
            },
        });
        renderVerificationStatus(selection, state);
        showSelectionToast(
            selectionToastElement,
            selectionToastMessage,
            selectionToast,
            state,
        );
    }
    const searchState = new TournamentSearchState({
        search(query) {
            return searchTournaments(searchEndpoint, query);
        },
        onChange(nextState) {
            renderStatus(status, nextState);
            renderResults(results, nextState.tournaments, selectTournament);
        },
    });

    function clearTournamentSearch() {
        input.value = "";
        searchState.clear();
    }

    async function selectTournament(tournament) {
        await picker.selectSearchResult(tournament);
        const verifiedTournamentId =
            picker.state.verifiedTournament?.tournament_id;
        if (
            picker.state.status === "verified"
            && verifiedTournamentId === tournament.tournament_id
        ) {
            clearTournamentSearch();
        }
    }

    // Show the addition area for the current source, which the browser may restore on reload.
    function showSourceAddition() {
        const rilton = sourceSelect.value === RILTON;
        memberAddition.hidden = rilton;
        riltonAddition.hidden = !rilton;
    }

    showSourceAddition();
    renderStatus(status, searchState.state);
    renderResults(results, searchState.state.tournaments, selectTournament);
    renderTournamentSelection(picker.state);
    renderSaveStatus(saveStatus, { status: "idle" });

    input.addEventListener("input", function handleSearchInput() {
        picker.clearStatus();
        searchState.setSearchText(input.value);
    });
    pastedIdInput.addEventListener("input", function handlePastedIdInput() {
        picker.clearStatus();
    });
    pastedIdForm.addEventListener("submit", function handlePastedId(event) {
        event.preventDefault();
        const tournamentId = pastedIdInput.value;
        pastedIdInput.value = "";
        clearTournamentSearch();
        picker.verifyTournamentId(tournamentId);
    });
    // A change of source discards a pending verification, so a late answer
    // cannot add a tournament from the source the operator left.
    sourceSelect.addEventListener("change", function handleSourceChange() {
        picker.clearStatus();
        clearTournamentSearch();
        showSourceAddition();
    });
    riltonUrlInput.addEventListener("input", function handleRiltonUrlInput() {
        picker.clearStatus();
    });
    riltonUrlForm.addEventListener("submit", function handleRiltonUrl(event) {
        event.preventDefault();
        picker.verifyRiltonUrl(riltonUrlInput.value);
    });
    removeAllButton.addEventListener(
        "click",
        requestAllTournamentsRemoval,
    );
    confirmRemovalButton.addEventListener(
        "click",
        function confirmTournamentRemoval() {
            if (pendingRemoval === null || stale) {
                return;
            }
            const removal = pendingRemoval;
            pendingRemoval = null;
            if (removal.kind === "all") {
                picker.removeAllTournaments();
            } else {
                picker.removeTournament(removal.key);
            }
            removalDialog.hide();
        },
    );
    removalDialogElement.addEventListener(
        "hidden.bs.modal",
        function clearTournamentPendingRemoval() {
            pendingRemoval = null;
            render(nothing, removalTournamentName);
        },
    );
    globalThis.addEventListener(
        "senior:before-navigation",
        function persistBeforeNavigation(event) {
            // A change of season or language discards a pending verification.
            picker.clearStatus();
            event.detail.waitUntil(saveQueue.pending);
        },
    );
    // Warn before the page closes or follows a link while a save is queued or
    // running, or while a verified Rilton tournament waits to be added. A
    // season or language change has already waited for its saves and
    // discarded the verification.
    globalThis.addEventListener(
        "beforeunload",
        function warnBeforeLosingChanges(event) {
            if (saveQueue.busy || picker.state.status === "pending_addition") {
                event.preventDefault();
                // Older browsers show the prompt only when this is set.
                event.returnValue = "";
            }
        },
    );
    return picker;
}

for (const root of document.querySelectorAll("[data-tournament-search]")) {
    mountTournamentSearch(root);
}
