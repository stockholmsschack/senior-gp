import assert from "node:assert/strict";

import {
    OPERATION_STORAGE_KEY,
    followOperation,
    progressPercentage,
    rememberOperation,
    rememberedStatusUrl,
} from "../../senior_gp/web/static/js/generation-operation.js";

class MemoryStorage {
    constructor() {
        this.items = new Map();
    }

    getItem(key) {
        return this.items.has(key) ? this.items.get(key) : null;
    }

    setItem(key, value) {
        this.items.set(key, value);
    }

    removeItem(key) {
        this.items.delete(key);
    }
}

function operation(eventId, { terminal = false, progress = {} } = {}) {
    return {
        status_url: "/api/v1/generation/operations/abc",
        latest_event_id: eventId,
        terminal,
        events: [{ event_id: eventId, progress }],
    };
}

// Run the follower on manual timers. `answers` holds operations or errors.
function manualFollower(answers, latestEventId = 1) {
    const timers = [];
    const seen = [];
    const errors = [];
    const follower = followOperation({
        statusUrl: "/status",
        latestEventId,
        readStatus() {
            const answer = answers.shift();
            return answer instanceof Error
                ? Promise.reject(answer)
                : Promise.resolve(answer);
        },
        onOperation(updated) {
            seen.push(updated.latest_event_id);
        },
        onError(error) {
            errors.push(error.message);
        },
        schedule(callback) {
            timers.push(callback);
            return timers.length;
        },
        cancel(timer) {
            timers[timer - 1] = null;
        },
    });
    async function tick() {
        const callback = timers.findLast((timer) => timer !== null);
        timers.fill(null);
        await callback();
    }
    return { follower, timers, seen, errors, tick };
}

// A running operation is remembered and a finished one is forgotten.
{
    const storage = new MemoryStorage();
    rememberOperation(storage, operation(2));
    assert.equal(rememberedStatusUrl(storage), "/api/v1/generation/operations/abc");

    rememberOperation(storage, operation(5, { terminal: true }));
    assert.equal(rememberedStatusUrl(storage), null);
}

// Unreadable or blocked storage restores nothing and does not throw.
{
    const storage = new MemoryStorage();
    storage.setItem(OPERATION_STORAGE_KEY, "not json");
    assert.equal(rememberedStatusUrl(storage), null);

    const blocked = {
        getItem() {
            throw new Error("blocked");
        },
        setItem() {
            throw new Error("blocked");
        },
        removeItem() {
            throw new Error("blocked");
        },
    };
    const warn = console.warn;
    console.warn = () => {};
    try {
        rememberOperation(blocked, operation(2));
        assert.equal(rememberedStatusUrl(blocked), null);
    } finally {
        console.warn = warn;
    }
}

// The bar counts finished stages, and is indeterminate without a count.
{
    assert.equal(progressPercentage(operation(3, { progress: { completed: 1, total: 4 } })), 25);
    assert.equal(progressPercentage(operation(2)), null);
    assert.equal(progressPercentage({ events: [] }), null);
}

// Polling reports each newer state once, reports the state again after a
// failed read, and stops when the operation finishes.
{
    const { timers, seen, errors, tick } = manualFollower([
        operation(1),
        operation(2),
        new Error("offline"),
        operation(2),
        operation(2),
        operation(4, { terminal: true }),
    ]);
    for (let read = 0; read < 6; read += 1) {
        await tick();
    }

    assert.deepEqual(seen, [2, 2, 4]);
    assert.deepEqual(errors, ["offline"]);
    assert.ok(timers.every((timer) => timer === null));
}

// A check during a read reads once more instead of reading in parallel,
// and leaves one timer.
{
    let release;
    const reads = [];
    const timers = [];
    const follower = followOperation({
        statusUrl: "/status",
        readStatus() {
            reads.push("read");
            return reads.length === 1
                ? new Promise((resolve) => {
                    release = () => resolve(operation(2));
                })
                : Promise.resolve(operation(3));
        },
        onOperation() {},
        schedule(callback) {
            timers.push(callback);
            return timers.length;
        },
        cancel(timer) {
            timers[timer - 1] = null;
        },
    });
    const first = follower.check();
    await follower.check();
    assert.equal(reads.length, 1);
    release();
    await first;

    assert.equal(reads.length, 2);
    assert.equal(timers.filter((timer) => timer !== null).length, 1);
    follower.close();
    assert.ok(timers.every((timer) => timer === null));
}

// A failing callback on a finished operation still stops the polling.
{
    const timers = [];
    const follower = followOperation({
        statusUrl: "/status",
        readStatus: () => Promise.resolve(operation(3, { terminal: true })),
        onOperation() {
            throw new Error("render failed");
        },
        schedule(callback) {
            timers.push(callback);
            return timers.length;
        },
        cancel(timer) {
            timers[timer - 1] = null;
        },
    });
    await follower.check().catch(() => {});

    assert.ok(timers.every((timer) => timer === null));
}

// A hub message reads the status at once, and closing ends the subscription.
// Without a hub URL, the follower opens no subscription.
{
    const sources = [];
    function eventSourceFactory(url) {
        const source = {
            url,
            listeners: {},
            closed: false,
            addEventListener(kind, listener) {
                this.listeners[kind] = listener;
            },
            close() {
                this.closed = true;
            },
        };
        sources.push(source);
        return source;
    }
    const seen = [];
    const follower = followOperation({
        statusUrl: "/status",
        hubUrl: "https://portal.example/.well-known/mercure",
        topic: "https://stockholmsschack.se/senior/operations/abc",
        eventSourceFactory,
        readStatus: () => Promise.resolve(operation(2)),
        onOperation(updated) {
            seen.push(updated.latest_event_id);
        },
        schedule: () => 1,
        cancel() {},
    });
    assert.equal(
        sources[0].url,
        "https://portal.example/.well-known/mercure?topic="
            + encodeURIComponent("https://stockholmsschack.se/senior/operations/abc"),
    );
    await sources[0].listeners.message();
    assert.deepEqual(seen, [2]);
    follower.close();
    assert.equal(sources[0].closed, true);

    followOperation({
        statusUrl: "/status",
        topic: "https://stockholmsschack.se/senior/operations/abc",
        eventSourceFactory,
        readStatus: () => Promise.resolve(operation(2)),
        onOperation() {},
        schedule: () => 1,
        cancel() {},
    });
    assert.equal(sources.length, 1);
}
