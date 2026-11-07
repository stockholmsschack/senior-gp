"""Run web generations in the background and record each one as a durable operation.

Each operation is one JSON record under `<state>/operations/`, following
JGP's generation operations. A record holds the captured season, the
configuration revision, the generation date and the actor, and every event
from acceptance to completion or failure. The status endpoint reads the
record, so the record survives a restart.

One application-wide lease, `<state>/operations/generation.lease`, lets one
generation run at a time. Its owner holds an exclusive `flock` on it, which
the kernel releases when the owning process exits. When a start finds a lease
that no process locks, it marks the lease's operation failed at stage
`interrupted`, removes the lease and takes it. Creating the manager does the
same, and also fails every other unfinished operation, because no process
runs it. Clearing a season's downloads takes the same lease, so a clear and
a generation never overlap.

A host may pass a publisher, such as a Mercure publisher, that receives each
transition after its record is written. Delivery is best effort: the record
stays the source of truth, and a publisher that raises changes nothing.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, replace
from datetime import date
import fcntl
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Protocol
from uuid import uuid4

from ..atomic_write import atomic_replace_text
from ..configuration import ActiveConfiguration
from ..publication import clear_season
from ..service import STAGES, GenerationRun, run_generation

OPERATIONS_DIRECTORY = "operations"
LEASE_FILENAME = "generation.lease"
INTERRUPTED_STAGE = "interrupted"
TOPIC_PREFIX = "https://stockholmsschack.se/senior/operations"
LOGGER = logging.getLogger(__name__)

GenerationRunner = Callable[..., GenerationRun]


class GenerationBusyError(RuntimeError):
    """Another generation holds the lease. `operation_id` names it, or is empty when the lease cannot be read."""

    def __init__(self, operation_id: str) -> None:
        self.operation_id = operation_id
        super().__init__(f"generation operation {operation_id} is running")


@dataclass(frozen=True)
class OperationEvent:
    """One step of an operation: `accepted`, `stage`, `completed` or `failed`.

    A `stage` event's `progress` counts the stages finished before it, such as `{"completed": 1, "total": 4}`.
    """

    event_id: int
    kind: str
    message_key: str
    parameters: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationOperation:
    """The durable state of one web generation and the inputs it captured when it started."""

    operation_id: str
    status_url: str
    state: str
    season: int
    configuration_revision: int
    generated_on: str
    actor: Any
    latest_event_id: int
    terminal: bool
    run_id: str | None = None
    failure_stage: str | None = None
    events: tuple[OperationEvent, ...] = ()
    topic: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class TransitionPublisher(Protocol):
    """The sibling tools' publisher method, which the host's `MERCURE_PUBLISHER` setting supplies.

    `publish` runs on the generation's thread, so it must return at once, for example by queuing the delivery.
    """

    def publish(self, topic: str, operation_id: str, status_url: str, transition: OperationEvent,
                operation_data: dict[str, Any]) -> None: ...


class OperationStore:
    """Write and read operation records, and grant the generation lease."""

    def __init__(self, state_directory: Path, url_prefix: str = "",
                 publisher: TransitionPublisher | None = None) -> None:
        self.directory = Path(state_directory) / OPERATIONS_DIRECTORY
        self._url_prefix = url_prefix
        self._publisher = publisher
        self._lease_path = self.directory / LEASE_FILENAME
        self._held: dict[str, int] = {}
        self._lock = threading.RLock()

    def acquire(self, operation_id: str) -> None:
        """Take the lease for the operation, or raise GenerationBusyError while another operation holds it."""
        self.directory.mkdir(parents=True, exist_ok=True)
        # Lock a new file, then link it into place, so the lease never exists unlocked.
        descriptor, temporary = tempfile.mkstemp(dir=self.directory, prefix=".lease-")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.write(descriptor, f"{operation_id}\n".encode())
            os.fsync(descriptor)
            with self._lock:
                try:
                    os.link(temporary, self._lease_path)
                except FileExistsError:
                    self.recover()
                    os.link(temporary, self._lease_path)
                self._held[operation_id] = descriptor
        except FileExistsError as error:
            os.close(descriptor)
            raise GenerationBusyError(self.lease_owner()) from error
        except BaseException:
            os.close(descriptor)
            raise
        finally:
            try:
                os.unlink(temporary)
            except OSError:
                LOGGER.warning("cannot remove the temporary lease file %s", temporary)

    def recover(self) -> None:
        """When no process holds the lease, fail its operation at stage `interrupted` and remove the lease."""
        try:
            descriptor = os.open(self._lease_path, os.O_RDONLY)
        except FileNotFoundError:
            return
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Another process may have replaced the lease before this one locked it.
            if os.fstat(descriptor).st_ino != os.stat(self._lease_path).st_ino:
                return
            # Read the owner from the locked file, which nobody else can replace now.
            operation_id = os.read(descriptor, 256).decode("utf-8", "replace").strip()
            self._interrupt(operation_id)
            self._lease_path.unlink()
        except (BlockingIOError, FileNotFoundError):
            pass  # The owner is running, or it released the lease meanwhile.
        finally:
            os.close(descriptor)

    def fail_unfinished(self) -> None:
        """Fail at stage `interrupted` every unfinished operation that does not hold the lease.

        Call it only after `recover`, when any remaining lease belongs to a running process.
        """
        owner = self.lease_owner()
        for path in self.directory.glob("*.json"):
            if path.stem != owner:
                self._interrupt(path.stem, only_unfinished=True)

    def _interrupt(self, operation_id: str, *, only_unfinished: bool = False) -> None:
        try:
            if only_unfinished and self.load(operation_id).terminal:
                return
            self.transition(operation_id, kind="failed", message_key="operations.failed",
                            parameters={"stage": INTERRUPTED_STAGE, "detail": "the server stopped during the run"},
                            failure_stage=INTERRUPTED_STAGE)
        except (FileNotFoundError, RuntimeError):
            # The lease names no readable record, or the operation had already finished.
            return
        LOGGER.warning("generation %s was interrupted", operation_id)

    def release(self, operation_id: str) -> None:
        """Remove the lease that the operation holds, if any."""
        with self._lock:
            descriptor = self._held.pop(operation_id, None)
            if descriptor is not None:
                self._lease_path.unlink(missing_ok=True)
                os.close(descriptor)

    def lease_owner(self) -> str:
        """Return the ID of the operation that holds the lease, or an empty string."""
        try:
            return self._lease_path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def status_url(self, operation_id: str) -> str:
        return f"{self._url_prefix}/api/v1/generation/operations/{operation_id}"

    @staticmethod
    def topic(operation_id: str) -> str:
        return f"{TOPIC_PREFIX}/{operation_id}"

    def create(self, operation: GenerationOperation) -> None:
        with self._lock:
            self._write(operation)
        self._publish(operation, operation.events[-1])

    def load(self, operation_id: str) -> GenerationOperation:
        """Return the operation, or raise FileNotFoundError for an unknown or unreadable ID."""
        if not operation_id or any(character not in "0123456789abcdef" for character in operation_id):
            raise FileNotFoundError(operation_id)
        try:
            document = json.loads(self._path(operation_id).read_text(encoding="utf-8"))
            operation = _operation_from_dict(document)
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise FileNotFoundError(operation_id) from error
        # The record may predate the current mount prefix or the topic.
        return replace(operation, status_url=self.status_url(operation_id), topic=self.topic(operation_id))

    def transition(self, operation_id: str, *, kind: str, message_key: str, parameters: dict[str, Any] | None = None,
                   progress: dict[str, int] | None = None, run_id: str | None = None,
                   failure_stage: str | None = None) -> GenerationOperation:
        """Append an event and return the updated operation. A completed or failed operation takes no further events."""
        with self._lock:
            current = self.load(operation_id)
            if current.terminal:
                raise RuntimeError(f"operation {operation_id} has already finished")
            event = OperationEvent(current.latest_event_id + 1, kind, message_key, dict(parameters or {}),
                                   dict(progress or {}))
            terminal = kind in ("completed", "failed")
            updated = replace(
                current,
                state=kind if terminal else "running",
                latest_event_id=event.event_id,
                terminal=terminal,
                run_id=run_id,
                failure_stage=failure_stage,
                events=(*current.events, event),
            )
            self._write(updated)
        self._publish(updated, event)
        return updated

    def _publish(self, operation: GenerationOperation, event: OperationEvent) -> None:
        if self._publisher is None:
            return
        try:
            self._publisher.publish(operation.topic, operation.operation_id, operation.status_url, event,
                                    operation.as_dict())
        except Exception:
            LOGGER.warning("cannot publish event %s of generation %s", event.event_id, operation.operation_id,
                           exc_info=True)

    def _path(self, operation_id: str) -> Path:
        return self.directory / f"{operation_id}.json"

    def _write(self, operation: GenerationOperation) -> None:
        atomic_replace_text(self._path(operation.operation_id),
                            json.dumps(operation.as_dict(), ensure_ascii=False, separators=(",", ":")) + "\n")


class GenerationOperationManager:
    """Start generations on an executor, by default with one worker, and record their progress."""

    def __init__(
        self,
        state_directory: Path,
        output_directory: Path,
        *,
        rilton_fetch: Callable | None = None,
        executor: Executor | None = None,
        runner: GenerationRunner | None = None,
        url_prefix: str = "",
        publisher: TransitionPublisher | None = None,
    ) -> None:
        self.store = OperationStore(state_directory, url_prefix, publisher)
        self.state_directory = Path(state_directory)
        self.output_directory = Path(output_directory)
        self._rilton_fetch = rilton_fetch
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="senior-generation")
        self._runner = runner or run_generation
        try:
            self.store.recover()
            self.store.fail_unfinished()
        except OSError:
            LOGGER.exception("cannot recover interrupted generations")

    def clear_season(self, season: int) -> None:
        """Remove the season's generated files under the lease, so that no generation runs meanwhile.

        Raise GenerationBusyError while a generation holds the lease.
        """
        cleanup_id = f"clear-{uuid4().hex}"
        self.store.acquire(cleanup_id)
        try:
            clear_season(self.output_directory, season)
        finally:
            self.store.release(cleanup_id)

    def start(self, configuration: ActiveConfiguration, today: date, actor: Any = None) -> GenerationOperation:
        """Take the lease, record a new operation for the configuration snapshot, and submit its run.

        Raise GenerationBusyError while another generation holds the lease.
        """
        operation_id = uuid4().hex
        operation = GenerationOperation(
            operation_id=operation_id,
            status_url=self.store.status_url(operation_id),
            topic=self.store.topic(operation_id),
            state="accepted",
            season=configuration.season,
            configuration_revision=configuration.revision,
            generated_on=today.isoformat(),
            actor=actor,
            latest_event_id=1,
            terminal=False,
            events=(OperationEvent(1, "accepted", "operations.accepted"),),
        )
        self.store.acquire(operation_id)
        try:
            self.store.create(operation)
        except BaseException:
            self.store.release(operation_id)
            raise
        try:
            self._executor.submit(self._run, operation_id, configuration, today)
        except Exception as error:
            try:
                self.store.transition(operation_id, kind="failed", message_key="operations.failed",
                                      parameters={"stage": "scheduling", "detail": str(error)},
                                      failure_stage="scheduling")
            finally:
                self.store.release(operation_id)
            raise
        return operation

    def _run(self, operation_id: str, configuration: ActiveConfiguration, today: date) -> None:
        stage = "starting"

        def report_stage(name: str) -> None:
            nonlocal stage
            stage = name
            progress = {"completed": STAGES.index(name), "total": len(STAGES)} if name in STAGES else {}
            self.store.transition(operation_id, kind="stage", message_key="operations.stage",
                                  parameters={"stage": name}, progress=progress)

        try:
            try:
                run = self._runner(configuration, self.state_directory, self.output_directory, today=today,
                                   rilton_fetch=self._rilton_fetch, report_stage=report_stage)
            except Exception as error:
                # `stage` is the reported stage. The detail names the failed input, such as one tournament.
                LOGGER.warning("generation %s failed at %s: %s", operation_id, stage, error)
                self.store.transition(operation_id, kind="failed", message_key="operations.failed",
                                      parameters={"stage": stage, "detail": str(error)}, failure_stage=stage)
                return
            self.store.transition(operation_id, kind="completed", message_key="operations.completed",
                                  parameters={"run_id": run.directory.name, "warnings": list(run.result.warnings)},
                                  run_id=run.directory.name)
        except Exception:
            # Nobody reads the executor's result, so log a record that cannot be written.
            LOGGER.exception("cannot record the outcome of generation %s", operation_id)
        finally:
            self.store.release(operation_id)


def _operation_from_dict(document: dict[str, Any]) -> GenerationOperation:
    return GenerationOperation(
        operation_id=str(document["operation_id"]),
        status_url=str(document["status_url"]),
        state=str(document["state"]),
        season=int(document["season"]),
        configuration_revision=int(document["configuration_revision"]),
        generated_on=str(document["generated_on"]),
        actor=document.get("actor"),
        latest_event_id=int(document["latest_event_id"]),
        terminal=bool(document["terminal"]),
        run_id=document.get("run_id"),
        failure_stage=document.get("failure_stage"),
        events=tuple(
            OperationEvent(int(event["event_id"]), str(event["kind"]), str(event["message_key"]),
                           dict(event.get("parameters", {})), dict(event.get("progress", {})))
            for event in document.get("events", [])
        ),
    )
