import { html, nothing, render } from "./lit-html.js";
import { translate } from "./locale.js";
import {
    followOperation,
    forgetOperation,
    progressPercentage,
    rememberOperation,
    rememberedStatusUrl,
} from "./generation-operation.js";

// Return the translation of a stage, or the stage itself, such as
// "tournament 5366 (Name)", when the catalogue has no entry for it.
function stageLabel(stage) {
    const key = `generation.stage.${stage}`;
    const label = translate(key);
    return label === key ? stage : label;
}

// Return the operation's one-line message and its Bootstrap tone.
function summary(operation) {
    const parameters = operation.events.at(-1)?.parameters ?? {};
    if (operation.state === "completed") {
        return {
            tone: "success",
            message: translate("generation.completed", {
                season: operation.season,
                run: operation.run_id,
            }),
        };
    }
    if (operation.state === "failed") {
        return {
            tone: "danger",
            message: translate("generation.failed", {
                season: operation.season,
                stage: stageLabel(operation.failure_stage),
            }),
        };
    }
    return {
        tone: "secondary",
        message: translate("generation.running", {
            season: operation.season,
            stage: parameters.stage
                ? stageLabel(parameters.stage)
                : translate("generation.stage.starting"),
        }),
    };
}

// Return a completed run's link to its files and its warnings, or a failed run's detail.
function details(operation, filesUrl) {
    const parameters = operation.events.at(-1)?.parameters ?? {};
    if (operation.state === "completed") {
        return html`
            <a class="alert-link ms-1" href=${filesUrl}>${translate("generation.files")}</a>
            ${parameters.warnings?.length
                ? html`<ul class="mb-0 mt-2">
                    ${parameters.warnings.map((warning) => html`<li>${warning}</li>`)}
                </ul>`
                : nothing}
        `;
    }
    if (operation.state === "failed" && parameters.detail) {
        return html`<div class="small mt-2">${parameters.detail}</div>`;
    }
    return nothing;
}

function renderInline(element, operation, filesUrl) {
    const { tone, message } = summary(operation);
    element.className = `alert alert-${tone} mt-3`;
    render(html`
        ${operation.terminal
            ? nothing
            : html`<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>`}
        ${message}
        ${details(operation, filesUrl)}
    `, element);
}

function progressBar(operation) {
    const percentage = progressPercentage(operation);
    return html`
        <div
            class="progress"
            role="progressbar"
            aria-label=${translate("generation.dialog.progress")}
            aria-valuemin="0"
            aria-valuemax="100"
            aria-valuenow=${percentage === null ? nothing : String(percentage)}
        >
            <div
                class="progress-bar ${percentage === null
                    ? "progress-bar-striped progress-bar-animated"
                    : ""}"
                style=${`width: ${percentage ?? 100}%`}
            ></div>
        </div>
        <p class="form-text mb-0 mt-2">${translate("generation.dialog.continues")}</p>
    `;
}

function renderDialog(element, operation, filesUrl) {
    const { tone, message } = summary(operation);
    render(html`
        <div class="alert alert-${tone} ${operation.terminal ? "mb-0" : ""}">
            ${message}
            ${details(operation, filesUrl)}
        </div>
        ${operation.terminal ? nothing : progressBar(operation)}
    `, element);
}

function renderError(element, messageKey) {
    element.className = "alert alert-danger mt-3";
    render(translate(messageKey), element);
}

function renderDialogError(element, messageKey) {
    render(html`<div class="alert alert-danger mb-0">${translate(messageKey)}</div>`, element);
}

async function readOperation(statusUrl) {
    const response = await fetch(statusUrl, {
        headers: { Accept: "application/json" },
    });
    if (!response.ok) {
        const error = new Error(`Operation status failed: ${response.status}`);
        error.status = response.status;
        throw error;
    }
    return (await response.json()).data;
}

export function mountGeneration(root) {
    const button = root.querySelector("[data-generate]");
    const blocked = root.querySelector("[data-generation-blocked]");
    const status = root.querySelector("[data-generation-status]");
    const dialog = root.querySelector("[data-generation-dialog]");
    const progress = dialog.querySelector("[data-generation-progress]");
    const storage = globalThis.localStorage;
    const filesUrl = root.dataset.filesUrl;
    const configuration = {
        revision: Number(root.dataset.configurationRevision),
        tournamentCount: Number(root.dataset.tournamentCount),
        saving: false,
        stale: false,
    };
    let starting = false;
    let current = null;
    let follower = null;

    // Return the message that says why Generate is disabled, or null.
    function blockedReason() {
        if (starting || (current && !current.terminal)) {
            return "generation.blocked.running";
        }
        if (configuration.stale) {
            return "generation.blocked.stale";
        }
        if (configuration.saving) {
            return "generation.blocked.saving";
        }
        if (configuration.tournamentCount === 0) {
            return "generation.blocked.no_tournaments";
        }
        return null;
    }

    function renderButton() {
        const reason = blockedReason();
        button.disabled = reason !== null;
        blocked.textContent = reason ? translate(reason) : "";
    }

    function showDialog() {
        globalThis.bootstrap.Modal.getOrCreateInstance(dialog).show();
    }

    function show(operation) {
        current = operation;
        rememberOperation(storage, operation);
        renderInline(status, operation, filesUrl);
        renderDialog(progress, operation, filesUrl);
        renderButton();
    }

    // Show the operation and read its status until it finishes.
    function follow(operation) {
        follower?.close();
        show(operation);
        if (operation.terminal) {
            follower = null;
            return;
        }
        follower = followOperation({
            statusUrl: operation.status_url,
            latestEventId: operation.latest_event_id,
            hubUrl: root.dataset.mercureHub,
            topic: operation.topic,
            readStatus: readOperation,
            onOperation: show,
            onError(error) {
                console.error(error);
                if (error.status === 404) {
                    // The record is gone, so no later read can succeed.
                    follower.close();
                    current = null;
                    forgetOperation(storage);
                    renderButton();
                }
                // A later successful read shows the run again.
                renderError(status, "errors.generation.status_unavailable");
                renderDialogError(progress, "errors.generation.status_unavailable");
            },
        });
    }

    // Return the started operation, or null after showing why none started.
    async function start() {
        let response;
        try {
            response = await fetch(root.dataset.startEndpoint, {
                method: "POST",
                headers: {
                    Accept: "application/json",
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ revision: configuration.revision }),
            });
        } catch (error) {
            console.error(error);
            renderError(status, "errors.generation.start_failed");
            return null;
        }
        const payload = await response.json().catch(() => ({}));
        if (response.ok) {
            return payload.data;
        }
        // Follow the running generation, even another season's.
        if (payload.error?.details?.operation) {
            return payload.error.details.operation;
        }
        configuration.stale ||= payload.error?.code === "stale_configuration";
        renderError(status, payload.error?.message_key ?? "errors.internal");
        return null;
    }

    button.addEventListener("click", async function generate() {
        starting = true;
        renderButton();
        try {
            const operation = await start();
            if (operation) {
                follow(operation);
                showDialog();
            }
        } finally {
            starting = false;
            renderButton();
        }
    });
    globalThis.addEventListener(
        "senior:configuration-state",
        function updateConfiguration(event) {
            Object.assign(configuration, event.detail);
            renderButton();
        },
    );
    renderButton();

    // After a reload, follow the remembered run. Reopen the dialog only while
    // it runs; a finished run shows its outcome once on the page. Generate
    // stays disabled until the read settles.
    const statusUrl = rememberedStatusUrl(storage);
    if (statusUrl) {
        starting = true;
        renderButton();
        readOperation(statusUrl).then(function restore(operation) {
            follow(operation);
            if (!operation.terminal) {
                showDialog();
            }
        }).catch(function keepUnlessGone(error) {
            console.warn(error);
            // Keep the run for the next load unless its record is gone.
            if (error.status === 404) {
                forgetOperation(storage);
            } else {
                renderError(status, "errors.generation.status_unavailable");
            }
        }).finally(function allowGenerate() {
            starting = false;
            renderButton();
        });
    }
}

for (const root of document.querySelectorAll("[data-generation]")) {
    mountGeneration(root);
}
