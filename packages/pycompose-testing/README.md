# pycompose-testing

Test PyCompose apps with no device: `AppDriver` starts an app through the same
session the phone runs, finds controls in the snapshots it publishes, and acts
on them as the host does; `Simulator` runs time, threads and randomness
deterministically. It runs on a developer's machine and in CI, never on a device.

See the repository for documentation: https://github.com/DagmawiKK/pycompose
