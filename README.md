# SDN-enabled edge–fog–cloud manufacturing experiments

Reproducibility package for **“Simulation-Based Evaluation of an SDN-Enabled
Edge-Fog-Cloud Architecture for Cloud Manufacturing Networks.”**

This repository contains experiment software, configuration, validation and
analysis. **No publication results are bundled.**

Two independent measurement systems are used:

* **iFogSim2:** simulated module execution, placement and device energy.
* **Mininet/OVS:** observed UDP service-path latency, jitter, delivery,
  deadline compliance, TCP throughput, outages, fault recovery and limited
  security-policy behavior.

Their latencies are never added or treated as interchangeable. The Mininet
service forwards a sensor datagram to the cell actuator; it does not simulate
the CPU work of the application modules. All reported numbers originate in
raw run files. Unit-test fixtures and smoke data are excluded from analysis.

## Source distribution status

This upload excludes the test suite and local validation artifacts at the repository owner's request.
`make test`, `make smoke`, `make preflight`, and `make reproduce` require restoring the omitted test suite; the validation gate has not been bypassed.

## Reproduce on a dedicated Ubuntu 22.04 x86-64 host

Run inside this repository. Use a local Linux filesystem, with no unrelated
Mininet topology or controller on TCP port 6653. Setup installs dependencies
and builds OVS 3.7.1 over the distribution OVS installation; use a dedicated
experiment host/VM. Windows is suitable for editing and pure Python tests,
but cannot execute the network experiments directly.

```bash
git submodule update --init --recursive
make setup
make capture-env
make topology
make test
make audit
make matrix
make smoke
make preflight
```

`make preflight` shows the repository tree, environment manifest, topology
validation, controller tests, one-seed smoke summary and result-constant audit.
It writes a source-bound gate only when they pass. The gate is invalidated by
source/configuration changes. Inspect the evidence before continuing:

```bash
make ifogsim
make mininet
make security
make analyze
make figures
make tables
make verify
```

From a **configured clean checkout without previous runs**, the equivalent is:

```bash
make reproduce
```

For an existing complete raw archive, regenerate analysis without rerunning:

```bash
make analysis-only
```

`make mininet` and `make security` need sudo for network namespaces. `make setup`
records resolved transitive dependencies. Python/Java patch versions, kernel,
hardware, software commits and OVS daemon version are captured automatically.
The supplied gitlinks pin iFogSim to
`643c433b9d6c9f031a2e31f129f2b2c6c7fae835` (v2.0.0) and Mininet to
`88f14e946a05cd0895e1a127bf89da9b3fb1d98b` (2.3.1b4).

## Data and execution

The main network matrix has 1,080 runs: phase 1 has 360 fault runs; phase 2 has
360 load runs; phase 3 has 120 paired security-overhead runs; phase 4 has 120
attack replications with both A2/A3 arms (240 runs). Each attack arm also
contains legitimate control probes. At 180 seconds per network run, measured
run time alone is 54 hours, plus setup, settling and collection. The separate
compute matrix has 360 runs (4 placements × 3 loads × 30 seeds).

Seeds 1001–1030 are the independent experimental units. Execution order is
randomized within seed and condition, with no concurrent experimental runs.
Completed compatible runs are resumed; failed runs remain sealed evidence
and stop resumption. Never edit or overwrite a failed raw run: archive the
entire campaign under a new directory/checkout and start a new campaign.

Supplemental 1/5/10 ms flapping runs are explicit, outside the main matrix:

```bash
sudo env PATH="$PATH" .venv/bin/python -m scripts.run_mininet --supplemental
```

Supplemental runs retain their own scenario names and must pass the same
validation before analysis. A 1 ms control period is an emulation stress
condition. Load multipliers change telemetry frequency and paced TCP offered
load, never the control period.

```
config/             Experimental inputs and software pins
mininet/            Topology model, UDP tools, security probes, OF1.3 controller
ifogsim/            Java compute-placement experiment
analysis/           Raw reduction, statistics, figures, tables
scripts/            Setup, capture, runners, preflight, strict verification
tests/              Controller/data/statistical unit tests
third_party/        Pinned upstream Git submodules
results/raw/        Separate sealed mininet/ and ifogsim/ run directories
results/smoke/      Smoke-only observations, never publication data
results/processed/  Seed-level metrics and raw-data provenance
results/statistics/ Descriptives, paired comparisons, omnibus comparisons
results/environment/ Captured environment and validation evidence
figures/            Automatically generated uncertainty plots
tables/             Automatically generated CSV and LaTeX tables
docs/               Protocol, metric definitions, reproducibility notes
```

Read [the experiment protocol](docs/EXPERIMENT_PROTOCOL.md),
[metric definitions](docs/METRIC_DEFINITIONS.md), and
[reproducibility details](docs/REPRODUCIBILITY.md) before interpreting results.
This is a limited source-binding/ACL experiment, not full zero-trust validation.
Author names, repository URL and any eventual Zenodo DOI must be supplied by
the actual authors when archiving; none has been invented here.
