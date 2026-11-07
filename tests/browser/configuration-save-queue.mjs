import assert from "node:assert/strict";

import { ConfigurationSaveQueue } from "../../senior_gp/web/static/js/configuration-save-queue.js";

function refusal(code) {
    const error = new Error("refused");
    error.code = code;
    return error;
}

function recordingQueue(answers) {
    const events = [];
    const requests = [];
    const queue = new ConfigurationSaveQueue({
        revision: 1,
        savedTournaments: ["a"],
        save(revision, tournaments) {
            requests.push([revision, tournaments]);
            const answer = answers.shift();
            return answer instanceof Error
                ? Promise.reject(answer)
                : Promise.resolve(answer);
        },
        onSaving() {
            events.push("saving");
        },
        onSaved(saved, latest) {
            events.push(["saved", saved.revision, latest]);
        },
        onFailure(error, savedTournaments, stale) {
            events.push(["failure", error.code, savedTournaments, stale]);
        },
    });
    return { queue, events, requests };
}

// Each save uses the revision that the previous save returned.
{
    const { queue, events, requests } = recordingQueue([
        { revision: 2, tournaments: ["a", "b"] },
        { revision: 3, tournaments: ["b"] },
    ]);
    assert.equal(queue.busy, false);
    queue.schedule(["a", "b"]);
    queue.schedule(["b"]);
    assert.equal(queue.busy, true);
    await queue.pending;
    assert.equal(queue.busy, false);
    assert.deepEqual(requests, [[1, ["a", "b"]], [2, ["b"]]]);
    assert.deepEqual(events, [
        "saving", "saving", ["saved", 2, false], ["saved", 3, true],
    ]);
}

// A refused save that is not stale restores the saved list, and the next
// change is saved.
{
    const { queue, events, requests } = recordingQueue([
        refusal("invalid_configuration"),
        { revision: 2, tournaments: ["c"] },
    ]);
    queue.schedule(["a", "b"]);
    await queue.pending;
    assert.deepEqual(events.at(-1), ["failure", "invalid_configuration", ["a"], false]);
    assert.equal(queue.schedule(["c"]), true);
    await queue.pending;
    assert.deepEqual(requests.at(-1), [1, ["c"]]);
    assert.deepEqual(events.at(-1), ["saved", 2, true]);
}

// A stale save reports even when a later save is queued, and stops that
// save and every later one.
{
    const { queue, events, requests } = recordingQueue([refusal("stale_configuration")]);
    queue.schedule(["a", "b"]);
    queue.schedule(["b"]);
    await queue.pending;
    assert.deepEqual(requests, [[1, ["a", "b"]]]);
    assert.deepEqual(events.at(-1), ["failure", "stale_configuration", ["a"], true]);
    assert.equal(queue.schedule(["c"]), false);
    await queue.pending;
    assert.equal(requests.length, 1);
}

// A failing callback does not stop later saves.
{
    const { queue, requests } = recordingQueue([
        { revision: 2, tournaments: ["b"] },
        { revision: 3, tournaments: ["c"] },
    ]);
    const onSaved = queue.onSaved;
    queue.onSaved = () => {
        queue.onSaved = onSaved;
        throw new Error("render failed");
    };
    const consoleError = console.error;
    console.error = () => {};
    queue.schedule(["b"]);
    await queue.pending;
    console.error = consoleError;
    queue.schedule(["c"]);
    await queue.pending;
    assert.deepEqual(requests, [[1, ["b"]], [2, ["c"]]]);
    assert.equal(queue.busy, false);
}

process.stdout.write("configuration save queue tests passed\n");
