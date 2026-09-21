# Validation workflow

Validation artifacts are generated under `results/environment/`:

* `environment_manifest.json`: command outputs, software versions, dependencies and environment checks.
* `topology_validation.json`: topology and link-disjoint path checks.
* `unit_tests.json` and `unit_tests.txt`: controller, packet, design, statistical and integrity checks.
* `constant_audit.json`: plotting-array audit.
* `repository_tree.txt`: package inventory.
* `development_validation.json`: development diagnostics, when generated.

Use Ubuntu 22.04 and OpenJDK 11 for target-environment validation.
The workflow covers kernel qdiscs, conventional RSTP, OS-Ken/OVS integration,
security probes, compute smoke runs and Mininet smoke runs.

`make preflight` checks the environment and source-bound validation evidence
before permitting the publication campaign. The full-matrix verifier checks
run coverage and raw-result integrity. See the README for commands.

Development diagnostics and smoke data are kept separate from publication data.
The test suite must be available to run the test-dependent validation commands.
