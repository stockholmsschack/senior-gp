import { translate } from "./locale.js";

function responseMessage(document, fallbackKey) {
    return translate(document?.error?.message_key ?? fallbackKey);
}

function showOutcome(element, message, successful) {
    element.textContent = message;
    element.className = successful ? "alert alert-success" : "alert alert-danger";
    element.setAttribute("role", successful ? "status" : "alert");
    element.focus();
}

// Clear one season's downloads after its dialog's confirmation, following
// JGP's Available files, and remove that season's rows from the page.
export function mountAvailableFiles(root, fetchRequest = globalThis.fetch) {
    const outcome = root.querySelector("[data-clear-outcome]");
    const fileList = root.querySelector("[data-file-list]");
    const emptyState = root.querySelector("[data-file-empty]");
    let clearing = false;

    async function clearSeason(confirmButton) {
        if (clearing) {
            return;
        }
        clearing = true;
        const season = confirmButton.dataset.season;
        confirmButton.disabled = true;
        confirmButton.textContent = confirmButton.dataset.busyLabel;
        try {
            const response = await fetchRequest(confirmButton.dataset.endpoint, {
                method: "POST",
                headers: { Accept: "application/json" },
            });
            const document = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(responseMessage(document, "errors.downloads.clear_failed"));
            }
            for (const row of root.querySelectorAll(`tr[data-season="${season}"]`)) {
                row.remove();
            }
            root.querySelector(`[data-clear-open="${season}"]`)?.remove();
            if (!root.querySelector("tr[data-season]")) {
                fileList?.classList.add("d-none");
                emptyState.classList.remove("d-none");
            }
            showOutcome(outcome, translate("files.clear.success", { season }), true);
        } catch (error) {
            console.error(error);
            const message = error instanceof Error && !(error instanceof TypeError)
                ? error.message
                : translate("errors.downloads.clear_failed");
            showOutcome(outcome, message, false);
        } finally {
            globalThis.bootstrap?.Modal.getOrCreateInstance(confirmButton.closest("[data-clear-dialog]")).hide();
            clearing = false;
            confirmButton.disabled = false;
            confirmButton.textContent = confirmButton.dataset.idleLabel;
        }
    }

    for (const confirmButton of root.querySelectorAll("[data-clear-confirm]")) {
        confirmButton.addEventListener("click", function confirmClear() {
            return clearSeason(confirmButton);
        });
    }
    return { clearSeason };
}

for (const root of document.querySelectorAll("[data-available-files]")) {
    mountAvailableFiles(root);
}
