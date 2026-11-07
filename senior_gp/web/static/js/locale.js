const catalogueElement = document.getElementById("locale-catalogue");
const catalogue = catalogueElement
    ? JSON.parse(catalogueElement.textContent)
    : {};

export function translate(key, parameters = {}) {
    const template = catalogue[key] ?? key;
    return template.replace(
        /\{([^{}]+)\}/g,
        function replaceParameter(match, name) {
            return Object.hasOwn(parameters, name) ? parameters[name] : match;
        },
    );
}

// A form marked `data-senior-navigation`, such as the language or season
// choice, submits only after every promise that a `senior:before-navigation`
// listener passes to `waitUntil` settles.
for (const form of document.querySelectorAll("form[data-senior-navigation]")) {
    form.addEventListener("submit", async function prepareNavigation(event) {
        event.preventDefault();
        const pending = [];
        globalThis.dispatchEvent(new CustomEvent(
            "senior:before-navigation",
            {
                detail: {
                    waitUntil(promise) {
                        pending.push(Promise.resolve(promise));
                    },
                },
            },
        ));
        await Promise.allSettled(pending);
        form.submit();
    });
}
