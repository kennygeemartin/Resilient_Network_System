# Validation status

The publication campaign has **not** been executed. This checkout was built
on Windows, where WSL has no installed Linux distribution. No Mininet/OVS
measurements, paper figures, paper tables or claimed architecture improvements
have been fabricated.

The test suite and local evidence are excluded from this GitHub distribution.
The following evidence exists only in the original development workspace under `results/environment/`:

* `environment_manifest.json`: real command outputs, exact available versions
  and explicit missing/incompatible dependencies. `ready` is false.
* `topology_validation.json`: pure-model validation of 7 switches, 17 hosts,
  27 links and link-disjoint fabric paths.
* `unit_tests.json` and `unit_tests.txt`: the latest executed controller,
  packet, paired-design, statistical and integrity checks.
* `constant_audit.json`: automated plotting-array audit and its limited scope.
* `repository_tree.txt`: package inventory.
* `development_validation.json`: non-target-platform Java diagnostics and
  their raw evidence locations, when generated.

The Java adapter compiles against the requested pinned iFogSim source with
`javac --release 11`. A development-only, one-seed simulation was executed
using the locally available Java 21 runtime. During development, the first
diagnostic exposed the distinction between upstream `stopSimulation()` and
`terminateSimulation()`; it was interrupted, preserved as failed evidence,
and corrected. Subsequent diagnostics are retained separately under
`results/development/ifogsim/`. These are not target-environment smoke results
and cannot satisfy the publication gate.

The controller tests exercise actual rule-generation code through an OpenFlow
message model, including every host pair under each configured uplink failure.
They also serialize all generated messages with OS-Ken 4.2.2 and launch the
real library against seven localhost OpenFlow protocol peers through handshake
and barrier completion. They do not prove kernel OVS behavior. A real UDP localhost test checks the
packet format, send/receive logging and monotonic clock calculations; it does
not substitute for Mininet.

Still required on Ubuntu 22.04/OpenJDK 11: dependency setup, kernel qdisc
validation, conventional RSTP integration, real OS-Ken/OVS integration, limited
security probe integration, target-platform compute smoke and the one-seed
Mininet smoke. Only a successful `make preflight` permits the 30-seed campaign.
The full-matrix verifier intentionally rejects the current empty raw-results
directories. Consult README for the exact commands.
