import { html, nothing } from "./lit-html.js";
import { translate } from "./locale.js";

function problemMessage(problem) {
    if (typeof problem === "string") {
        return problem;
    }
    return translate(problem.message_key, problem.parameters ?? {});
}

/** Render a server's problems, plain text or translation keys, as a list. */
export function problemList(problems = []) {
    if (problems.length === 0) {
        return nothing;
    }
    return html`
        <ul class="mb-0">
            ${problems.map(function problemItem(problem) {
                return html`<li>${problemMessage(problem)}</li>`;
            })}
        </ul>
    `;
}
