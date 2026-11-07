// Saves the season's tournament list one request at a time, each based on
// the revision that the previous save returned.
//
// When the latest save, or any save with a stale revision, is refused,
// `onFailure` receives the last saved list. A stale revision stops all later
// saves, because each would be refused too.
export class ConfigurationSaveQueue {
    constructor({
        revision,
        savedTournaments,
        save,
        onSaving,
        onSaved,
        onFailure,
    }) {
        this.revision = revision;
        this.savedTournaments = [...savedTournaments];
        this.stale = false;
        this.pending = Promise.resolve();
        this.save = save;
        this.onSaving = onSaving;
        this.onSaved = onSaved;
        this.onFailure = onFailure;
        this.version = 0;
        // The number of saves queued or running.
        this.unsettled = 0;
    }

    get busy() {
        return this.unsettled > 0;
    }

    // Queue a save of `tournaments`. Return false, and save nothing, once a
    // save has been refused as stale.
    schedule(tournaments) {
        if (this.stale) {
            return false;
        }
        const requested = [...tournaments];
        const version = ++this.version;
        this.onSaving();
        this.unsettled += 1;
        this.pending = this.pending.then(async () => {
            try {
                await this.#run(requested, version);
            } finally {
                this.unsettled -= 1;
            }
        }).catch((error) => {
            // Keep the queue running when a callback fails.
            console.error(error);
        });
        return true;
    }

    async #run(requested, version) {
        if (this.stale) {
            return;
        }
        let saved;
        try {
            saved = await this.save(this.revision, requested);
        } catch (error) {
            this.stale ||= error?.code === "stale_configuration";
            // A later save, already queued, reports its own outcome.
            // A stale refusal always reports, because the later save
            // will not run.
            if (version === this.version || this.stale) {
                this.onFailure(error, this.savedTournaments, this.stale);
            }
            return;
        }
        this.revision = saved.revision;
        this.savedTournaments = saved.tournaments;
        this.onSaved(saved, version === this.version);
    }
}
