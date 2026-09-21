# Reproducibility and provenance

## Pre-experiment gate

`make smoke` executes a short A3, seed-1001 network run with a real injected
link fault and a separate short compute simulation. It writes only under
`results/smoke`. It is not a substitute for the 30 independent replications.
`make preflight` checks environment versions, topology, actual generated
controller rules, result-array audit and successful smoke evidence, and shows
the evidence before writing a gate bound to the source hash. No full runner
accepts a missing/stale gate. Environment mismatch fails without fallback to
synthetic results. Local Windows tests do not satisfy the Linux gate.

## Raw data lifecycle

Each run exclusively creates its directory. All observations, metadata and
run-level summaries are generated there before finalization. Exceptions produce
failed metadata and retained logs; failed runs never become publication data.
At completion/failure a SHA-256 inventory is written and files become read-only.
Hash checks detect edits, missing files and extra files. This is an integrity
mechanism, not privileged-user-proof WORM storage. Archive raw trees to
versioned/object-locked storage with checksums for stronger immutability.

Publication analysis only reads `results/raw/mininet` and `results/raw/ifogsim`.
It writes new processed/statistical CSVs and figures/tables separately. Every
analysis output has provenance back to raw inventories. No manuscript results
are used as expected values. CI calculations use seed summaries, not packet
sample counts. The plotting module reads data-derived CSVs and is scanned
for numeric result arrays. The audit is deliberately limited: source review
is also necessary to establish the provenance of arbitrary scalar constants.

## Recovery and resumption

Main runners skip a completed, sealed run only when its source hash matches.
Runs are serial to prevent interference. Do not run multiple runners at once.
Never remove individual observations to improve a result. A failed run blocks
resumption; preserve that campaign and use a new checkout/campaign directory
after resolving the failure. If an external interruption leaves OVS resources,
inspect them, then run `sudo mn -c` on the dedicated experiment host. Cleanup
is not applied automatically to unrelated network state.

`make reproduce` is for a configured clean campaign. For interruption after a
passed smoke/preflight gate, resume `make ifogsim`, `make mininet`, and
`make security` directly. Re-running smoke in an existing run directory fails
instead of overwriting evidence. For analysis-only replication, keep the raw
archive and run `make analysis-only`; network privileges are unnecessary.

## Toolchain

Pinned source gitlinks are part of the repository; commit them together with
`.gitmodules` when publishing. The local initial scaffold has no invented Git
commit, author identity, public repository URL or DOI. Create the first real
commit before Linux capture/preflight so `git rev-parse HEAD` succeeds. Include
all implementation/configuration files and ensure the submodule states are
correct. A dirty-tree record is captured, and a content hash identifies exact
experiment code. Generated results should be deposited separately with hashes.

Top-level Python packages are pinned in `requirements.txt`; setup records the
fully resolved transitive environment in `requirements.resolved.txt`. Archive
the resolved requirements, downloaded wheels and OVS archive/checksum with the
campaign. OVS is downloaded from its official release endpoint; its downloaded
archive hash is captured, not represented as an independently authenticated
upstream signature. A future fresh resolver can select different transitive
packages; the archived lock/wheels are necessary for exact environment replay.

Primary upstream references:

* [iFogSim pinned source](https://github.com/Cloudslab/iFogSim/tree/643c433b9d6c9f031a2e31f129f2b2c6c7fae835)
* [Mininet pinned source](https://github.com/mininet/mininet/tree/88f14e946a05cd0895e1a127bf89da9b3fb1d98b)
* [Open vSwitch releases](https://www.openvswitch.org/download/)
* [OS-Ken 4.2.2](https://pypi.org/project/os-ken/4.2.2/)

The upstream submodules retain their own licenses. The top-level license
covers the new experiment package only. CITATION.cff is provisional software
metadata: the real authors should replace its organizational author entry,
add their affiliation/ORCID, repository URL and any assigned archive identifier
before deposition. Do not manufacture a DOI.
