# Experiment protocol

## Status and scope

This is a prospective, configurable experiment implementation. Parameters in
`config/experiment.yaml` are design inputs, not previous manuscript outputs.
Do not optimize parameters against historical results. Log any amendment in
the changelog before collecting a new campaign. The implementation is not
evidence that any architecture achieves a particular performance level.

Use one dedicated Ubuntu 22.04 x86-64 host, system Python 3.10, OpenJDK 11,
OVS 3.7.1, OS-Ken 4.2.2 and the pinned iFogSim/Mininet commits. Preserve the
exact environment manifest per run. CPU scheduling and Linux qdisc timing
limit emulation fidelity: a 10 Gbps configured link is a model parameter, not
a claim of achieved host forwarding capacity. Record load and scheduler
misses; do not silently discard overloaded runs.

Pinned Mininet's default TCIntf ceiling is 1 Gbps. The runner explicitly
extends that ceiling to the maximum configured rate and validates installed
kernel HTB rates and netem delays before starting. `tc_configuration.json`
retains both interface directions; a silently ignored 10 Gbps setting fails
the experiment setup.

## Topology and architecture factors

Four production cells each contain two sensors, an actuator, a fog host and
an access switch. Four access switches connect to both aggregation switches;
both aggregation switches connect to the core, which connects to cloud.
There are 7 switches, 17 hosts and 27 links. Link bandwidth/delay inputs:

| Link | Mbps | One-way ms |
|---|---:|---:|
| Sensor/actuator–access | 1000 | 0.25 |
| Fog–access | 10000 | 0.10 |
| Access–aggregation | 1000 | 0.50 |
| Aggregation–core | 10000 | 1.00 |
| Core–cloud | 1000 | 20.00 |

All inputs live in YAML. Host links are single-homed and are not protected
by the switch fabric's redundant uplinks. Neighbor entries are static in
every architecture to avoid ARP being an uncontrolled confounder. IPv6 is
not used for experiment traffic. DSCP marks are classified; no strict-priority
queue or admission-control guarantee is claimed.

| Architecture | Ingest/Filter/Control | Analytics/Storage | Forwarding | Security |
|---|---|---|---|---|
| A0 | Cloud | Cloud | OVS NORMAL + RSTP | Off |
| A1 | Local fog | Cloud | OVS NORMAL + RSTP | Off |
| A2 | Local fog | Cloud | OpenFlow 1.3 + fast failover | Off |
| A3 | Local fog | Cloud | Same as A2 | Binding + ACL |

A1/A2/A3 compute placement is identical. iFogSim does not model OpenFlow or
ACL processing overhead. A2–A3 network differences estimate the combined
binding/ACL overhead; comparing these iFogSim arms cannot establish network
security overhead. The packet forwarding relay performs no synthetic CPU delay.

## Workloads and pairing

The application graph is Sensor → Ingest → Filter → Control → Actuator, and
Filter → Analytics → Storage. iFogSim creates one module set per cell; the
two cell sensors share it. Edge, fog and cloud capacity/power inputs are
configurable. Power numbers are assumed profiles, not calibrated hardware
measurements. Tuple CPU demand, module RAM, analytic selectivity, event
resolution and resource-sampling period are explicit inputs.

C0 is 128-byte UDP, DSCP 46, every 5 ms in the principal matrix. C1 is 256-byte
UDP, DSCP 34, with seeded Poisson alarm arrivals. C2 is 512-byte UDP, DSCP 18,
with a nominal 100 ms interval, scaled down by the load multiplier. Packet
sizes include the experiment header and payload, excluding Ethernet/IP/UDP
overhead. C3 is TCP/iperf3, DSCP 0, paced per sensor at the YAML rate times
the load multiplier. Record achieved throughput instead of assuming pacing
targets were reached. The control deadline is separately configurable; its
default is a study assumption and is not a measured result.

For every seed/condition, deterministic workload construction produces alarm
times, sensor phases and a fault cell independently of architecture. Store
and hash the full realization. Within-seed architecture order is randomized
using a separate deterministic stream. Different seeds are independent run
replications; packets within a run are not statistical replications. The
iFogSim load scenarios replay the same offered C0/C1/C2 schedule, but use
simulation time and no TCP background computation. There is no latency
composition model.

## Fault timing

Runs last 180 seconds: 0–30 warm-up; 30–60 normal measurement; inject at 60;
fault active until 90; restore at 90; 90–150 recovery/post-fault; 150–180
stable post-fault. All metrics exclude warm-up, except explicitly labeled
whole-simulation compute energy. Packet receivers drain after the final
scheduled transmission. Warm-up and setup convergence are distinct.

Fault target is the seeded cell's access–g1 link, its fog attachment, or
both. Fog fail-stop suspends the fog service process (SIGSTOP, restored with
SIGCONT) and isolates its network attachment; actual process and interface
states are recorded. No CPU state loss or service migration is modeled. Link flapping
alternates down/up at 60/65/70/75/80/85 seconds. Record action-start and
action-completion monotonic timestamps; the nominal fault timestamp is
action-start, with the interval documenting injection uncertainty. Combined
failures are applied sequentially within that recorded interval.

Local sensor–fog–actuator cycles do not traverse the failed uplink. Their
unaffected behavior is valid evidence; do not imply an uplink recovery benefit
for these flows. Cloud-bound TCP traffic does traverse uplinks. Fog isolation
interrupts local service until restoration; fast failover cannot move the
application. A0 does not use the fog service. Report these exposure differences.

## Controller and limited security experiment

Table 0 admits host traffic and classifies DSCP. A3 additionally matches
ingress port, source MAC and source IPv4 address, and rejects host VLAN tags.
Table 1 implements allow-list segment/service ACLs (default drop for A3).
Table 2 forwards using precomputed paths. A2 traverses the same three tables
without binding/ACL restrictions. Unknown control/data traffic is not flooded.

Shortest-delay primary paths and edge-disjoint backup paths are precomputed
over the switch graph. Path VLANs prevent intermediate nodes from independently
bouncing packets onto a reverse backup. Fast-failover buckets monitor local
egress liveness. Destination-access detours handle reverse-direction access
link failure. Protection is tested for the specified access-uplink fault class;
this is not a general multi-failure routing guarantee. Pipeline installation
must finish with barrier replies from all switches before a run starts.

Port-status messages are detection evidence. Failover is proactive, so no
reactive FlowMod/reaction-time value is manufactured. First recovered packet
timestamps are derived from packet observations and retained in flow summaries.
RSTP architectures have no OS-Ken detection/reaction measurement.

Phase 4 sends four attack types: within-cell sensor-to-sensor traffic,
spoofed legitimate IP/MAC from the wrong sensor port, a forbidden actuator
service port, and sensor-to-actuator traffic across cells. A2 supplies the
unprotected delivery control and A3 supplies the protection arm. Every run
also sends a legitimate sensor-to-actuator flow. Receivers listen at attack
destinations even where access is denied, distinguishing policy drops from
absent applications. Inspect legitimate delivery and A2 delivery before
attributing loss to policy. These controls establish only the tested ACL and
binding behavior, not identity attestation, encrypted transport, or zero trust.

## Design constraints (not an implemented online ILP)

For flow f and directed link (u,v), let x[f,u,v] be the selected route, r[f]
its offered bit rate, d[u,v] its configured delay, and C[u,v] its capacity.

* Flow conservation: Σv x[f,u,v] − Σv x[f,v,u] = 1 at source, −1 at
  destination, and 0 elsewhere.
* Minimum-delay design objective: minimize Σ(u,v) d[u,v] x[f,u,v].
* Capacity constraint: Σf r[f] x[f,u,v] ≤ C[u,v]. This is a design constraint;
  offered-load tests may overload emulated links, and the controller implements
  no online capacity admission solver.
* Segment authorization: x[f,u,v] ≤ a[f], where a[f] is true only for allowed
  source/destination/protocol/service combinations with a valid binding.
* Protected-channel constraint: x[f,u,v] ≤ p[u,v] for flows requiring a
  protected channel. Encryption/channel protection is not implemented by these
  ACLs; no encrypted-channel or full zero-trust claim is supported.
* Primary/backup disjointness: x_primary[f,e] + x_backup[f,e] ≤ 1 on
  protected fabric edges. Single-homed attachment edges are outside this set.

The controller uses NetworkX shortest paths and explicit OpenFlow rules; it
does not solve an ILP online.

## Analysis plan

Compute seed-level metrics first. Report n, mean, sample SD, SE, 95% Student-t
CI, median and IQR for every scenario/architecture/metric. Unclipped t CIs
for bounded fractions are retained and labeled; do not reinterpret them as
physical bounds. Compare paired seed values using paired t tests after a
Shapiro–Wilk check of paired differences, otherwise Wilcoxon signed-rank.
Report B−A differences and CIs, Cohen's dz where defined, and matched-pairs
rank-biserial effects. Holm adjustment applies to all architecture pairs in
each tool/scenario/metric family; it does not imply global familywise control
over every exploratory endpoint.

Four-way comparisons use repeated-measures ANOVA only when residual normality
and a Mauchly sphericity approximation pass; otherwise Friedman, with partial
eta squared or Kendall's W. Singular covariance uses the conservative Friedman
branch. Identical pairs are explicitly identified. Constant nonzero paired
differences use Wilcoxon and leave dz undefined with a reason. Censored RTOs
are not substituted with zeros or discarded without accounting: descriptive
tables contain n_missing, and recovered-only RTO figures are labeled. Inferential
comparisons require at least 30 complete seed pairs. No p-value is reported
from an incomplete paired set. Assumption pretests are heuristic and the
stored diagnostics should accompany interpretation.
