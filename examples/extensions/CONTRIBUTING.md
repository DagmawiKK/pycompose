# Contributing Python integrations

HTTPX and SQLite live in `pycompose/integrations/`, outside the extension engine.
They have no privileged registration path. Import boundaries forbid core and CLI
code from importing concrete recipes. Their definitions use the same parser as
project-local contributor definitions.

## An ordinary independently packaged recipe

```python
from pycompose.extensions import Resource

def open_store(*, capacity=16):
    return Resource(
        lambda: MyLibraryClient(),
        close=lambda client: client.close(),
        workers=1,
        capacity=capacity,
    )
```

Use one resource in the app container, not a new executor on every tap. One worker
guarantees thread-affine open/use/close. More workers assert that your chosen
library object supports concurrent use. The resource opens lazily on its lane.
Normal library objects and return values stay in Python.

From a declared app action:

```python
container.store.submit(
    lambda client: client.read_record(record_id),
    success=record_arrived,
    failure=record_failed,
    encode=lambda record: {"title": record.title},
    error=lambda exc: {"error": type(exc).__name__},
    key="current-record",
    policy="latest",
)
```

Both targets are declared typed actions. Encoders use Python field names; the
framework validates fields and converts names to camelCase before delivery.
Exceptions are not sent across the bridge. The default failure payload is
`{"error": "ExceptionType"}`; supply an explicit mapper for another declared shape.
Mapper/encoding/delivery failures produce safe diagnostics, not recursive failure
actions. Choose application-safe error text rather than exposing tokens or bodies.

Handle `StateError` on submission explicitly: a closed/saturated resource never
promises a completion. `independent` admits separate requests, `latest` revokes
older interest for a key, and `single_flight` reuses a concurrent task for that key.
Keys are local to the resource. A single-flight caller must use the same operation
and result contract for a key; it is not a result cache.

`Task.cancel()` revokes queued outcomes, including those waiting in the native
queue. It may remove unstarted work but cannot stop arbitrary running threads or
undo external effects. Capacity includes physical obsolete work and unacknowledged
outcomes. No unbounded completion backlog is hidden behind the host queue.
Cancelled queued operations retain their slot until the executor dequeues their
closures; repeated submit/cancel cannot grow an unbounded physical executor queue.
Android extension delivery acknowledges thread-safe queue admission directly;
queue rejection retires the outcome and reports a safe diagnostic, allowing retry.
Legacy background delivery keeps its main-thread-marshalled callback.

Do not call `Task.result()` in an app action; that would block the state worker
and is refused. It is for external tests/scripts. It returns the original physical
result even when logical interest was cancelled after the operation started.

Resources used from worker actions are owned by that runtime session. Successful
reload retains resources and revokes old completion registrations; failed reload
preserves the working registrations. Session teardown closes used resources on
their lanes after physical work retires. `resource.close()` explicitly disposes a
screen-owned resource and returns a cleanup future without waiting on the worker.
Never wait for cleanup in an action. Independently used resources must be closed
by their caller. Unused resources never open or create threads.

Use `paths().files` for persistent private data and `paths().cache` for evictable
data. The host supplies those paths as strings before app construction; recipes
must not obtain native objects. Private storage is not automatically encrypted.

## Declarative requirements

Place `extensions/my_store.toml` inside the app project:

```toml
format = 1
interface = 1
id = "my_org.store"
version = "1.0.0"
requirements = ["my-library>=1,<2"]
scenarios = ["my_org.store.roundtrip"]
python_versions = ["3.12"]
abis = ["arm64-v8a", "x86_64"]
min_sdk = 24

[requires]
"python.serial" = 1
"python.actions" = 1

[optional]
"android.camera" = 1
```

Select the definition in `[extensions].definitions`. Paths must remain inside
the project and cannot traverse symlinks. Package your implementation as ordinary
app source or a named Python dependency; the definition never executes it.
The optional `modules` field selects reference implementations bundled in
`pycompose.integrations`, not external module discovery or import hooks.

Capability versions are exact contract-major matches in interface 1. Required
missing capabilities fail before build outputs change. Optional missing ones are
reported, not silently emulated. A declaration is a constraint, not compatibility
evidence. The plan reports the locked framework targets; custom native target
edits require actual build/device verification. Desktop pip is not the resolver
for Android artifacts. Resolution, packaging and operation evidence remain
`notRun` until those separate workflows execute.

Current contracts are bounded blocking execution, serial execution, worker action
delivery and explicitly configured Internet access. An async, stream, camera or
durable-job requirement is unavailable, not a request to substitute a thread pool.
New native contracts require reviewed registered source changes, schemas/versioning
where applicable, template parity and native/device tests. Installing a Python
package cannot load arbitrary native providers, grant permissions or extend IR.

## Run the shared conformance

```python
from pycompose.testing.extension_contract import ResourceContract

class TestMyStore(ResourceContract):
    expected = "known fixture value"

    def open_resource(self, *, capacity=16):
        return open_store(capacity=capacity)

    def operation(self, client):
        return client.read_fixture()
```

Run this class with pytest. It checks repeated library use, cleanup, closed-owner
rejection and the physical capacity retained by logically cancelled work. It is
stdlib-only tooling and is excluded from application artifacts. Add tests through
real app actions for payload mapping, stale results and error behavior, plus CLI
build and installed Android scenarios for target compatibility.

Use deterministic fixtures and publish exact versions, interpreter, ABI, API,
host/template, build mode, operation and artifact identities. A mock HTTP transport
is useful for Python conformance, but does not establish Android sockets or TLS.
An installed universal APK on one ABI does not establish execution on the other.
