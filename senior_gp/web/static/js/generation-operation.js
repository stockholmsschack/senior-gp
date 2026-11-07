// Follow a generation operation and remember it across a reload.

export const OPERATION_STORAGE_KEY = "senior:generation-operation";
export const POLL_INTERVAL_MS = 1000;

// Remember a running operation's status URL, and forget a finished one.
// Blocked storage only loses the restore after a reload.
export function rememberOperation(storage, operation) {
    if (operation.terminal) {
        forgetOperation(storage);
        return;
    }
    try {
        storage.setItem(
            OPERATION_STORAGE_KEY,
            JSON.stringify({ statusUrl: operation.status_url }),
        );
    } catch (error) {
        console.warn(error);
    }
}

// Return the remembered status URL, or null.
export function rememberedStatusUrl(storage) {
    try {
        const remembered = JSON.parse(storage.getItem(OPERATION_STORAGE_KEY));
        return typeof remembered?.statusUrl === "string"
            ? remembered.statusUrl
            : null;
    } catch {
        return null;
    }
}

export function forgetOperation(storage) {
    try {
        storage.removeItem(OPERATION_STORAGE_KEY);
    } catch (error) {
        console.warn(error);
    }
}

// Return the share of stages finished as a percentage, or null when the
// latest event does not count them.
export function progressPercentage(operation) {
    const progress = operation.events?.at(-1)?.progress ?? {};
    const completed = Number(progress.completed);
    const total = Number(progress.total);
    if (!Number.isFinite(completed) || !Number.isFinite(total) || total <= 0) {
        return null;
    }
    return Math.min(100, Math.max(0, Math.round((completed / total) * 100)));
}

// Read the operation's status every `interval` until it finishes. Pass each
// newer state, and the first state read after a failed read, to
// `onOperation`. Pass each failed read to `onError`. With a `hubUrl`, also
// subscribe to the operation's `topic` there, and read the status at once when
// the subscription opens and on each message. Polling continues, so a lost message only delays the update.
// `check` reads the status at once. Return `{ check, close }`.
export function followOperation({
    statusUrl,
    latestEventId = 0,
    readStatus,
    onOperation,
    onError = () => {},
    interval = POLL_INTERVAL_MS,
    schedule = (callback, delay) => setTimeout(callback, delay),
    cancel = (timer) => clearTimeout(timer),
    hubUrl = "",
    topic = "",
    eventSourceFactory = (url) => new EventSource(url),
}) {
    let closed = false;
    let timer = null;
    let reading = false;
    let readAgain = false;
    let lastReadFailed = false;
    let events = null;

    function close() {
        closed = true;
        if (timer !== null) {
            cancel(timer);
            timer = null;
        }
        events?.close();
    }

    async function check() {
        if (closed) {
            return;
        }
        if (reading) {
            readAgain = true;
            return;
        }
        if (timer !== null) {
            cancel(timer);
            timer = null;
        }
        reading = true;
        try {
            do {
                readAgain = false;
                try {
                    const operation = await readStatus(statusUrl);
                    const newer = operation.latest_event_id > latestEventId;
                    if (!closed && (newer || lastReadFailed)) {
                        lastReadFailed = false;
                        latestEventId = Math.max(latestEventId, operation.latest_event_id);
                        // Close first, so a failing `onOperation` cannot keep polling a finished run.
                        if (operation.terminal) {
                            close();
                        }
                        onOperation(operation);
                    }
                } catch (error) {
                    if (!closed) {
                        lastReadFailed = true;
                        onError(error);
                    }
                }
            } while (readAgain && !closed);
        } finally {
            reading = false;
        }
        if (!closed) {
            timer = schedule(check, interval);
        }
    }

    timer = schedule(check, interval);
    if (hubUrl && topic) {
        try {
            const subscription = new URL(hubUrl, globalThis.location?.origin);
            subscription.searchParams.append("topic", topic);
            events = eventSourceFactory(subscription.toString());
            // Read on open too, for an event published before the subscription.
            events.addEventListener("open", function readOnOpen() {
                return check();
            });
            events.addEventListener("message", function readAtOnce() {
                return check();
            });
        } catch (error) {
            // Polling alone still follows the run.
            console.warn(error);
        }
    }
    return { check, close };
}
