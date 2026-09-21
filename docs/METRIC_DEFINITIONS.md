# Metric definitions

All network timestamps use `time.monotonic_ns()` in Linux namespaces on one
kernel. They are not wall-clock timestamps and are not comparable across hosts
or separate runs. No clock synchronization is required within this topology.
Packet headers contain a magic/version marker, flow ID, sequence, class,
scheduled timestamp, actual send timestamp and deadline duration. Packet-level
receiver CSVs add run, architecture, scenario, seed, receive time and outcomes.

| Metric | Operational definition |
|---|---|
| Observed packet latency | Actuator receive − actual sensor send, for uniquely received packets; includes relay and emulation overhead |
| Deadline compliance | Actuator receive − scheduled cycle timestamp ≤ configured class deadline |
| Jitter | Mean absolute difference of one-way latencies for adjacent sequence numbers when both are received; flow mean then equal-flow mean |
| Service availability | Deadline-compliant C0 cycles / scheduled C0 cycles during measurement; includes sender scheduling failures |
| Packet loss fraction | 1 − unique received / scheduled, including sender misses; sender ledger permits separate network-only analysis |
| UDP throughput | Received application datagram bytes × 8 / measurement seconds, summed across flows |
| TCP throughput | iperf3 receiver bytes / receiver interval duration, summed across streams, excluding intervals outside the measurement window |
| Total observed outage | Wall-clock union of failed C0 cycle intervals across flows, each interval extending to that flow's next scheduled cycle |
| Summed flow outage | Sum of per-flow failed-cycle intervals; may exceed run duration because flows overlap |
| Mean flow outage | Summed flow outage divided by number of critical flows |
| Fault detection | Matching port-down status timestamp − fault-action start; injection start/end bound action uncertainty |
| Controller reaction | Reactive flow-update timestamp − detection; not applicable for preinstalled fast-failover groups |
| RTO, per flow | First receive timestamp in the first five sequence-consecutive successful deadline-compliant C0 cycles scheduled after fault − fault-action start |
| RTO, run | Maximum per-flow RTO among the seeded fault cell's two critical sensor flows; both must recover; otherwise right-censored |
| Attack block rate | 1 − unique attack probes received / attack probes sent |
| Authorized allow rate | Unique legitimate probes received / legitimate probes sent |
| False block rate | 1 − authorized allow rate; observed non-delivery, requiring A2 control interpretation |
| Security overhead | Within-seed A3−A2 metric difference under the same offered load and workload |

`packets.csv` retains duplicates; summary counts use the first receipt per
flow/sequence. Sender logs enumerate every planned cycle and label `sent`,
`scheduler_miss` or `send_error`. No catch-up burst is sent for a cycle already
beyond its deadline. A receive after the measurement interval can count for a
cycle scheduled inside it, if the receiver drain captures it and its deadline
was met. Lost or unsent packets never acquire an invented latency. Empty or
undefined metrics have explicit reasons.

RTO reports restoration of a sequence of valid service cycles, not switch
convergence in isolation. Unaffected flows still have a time to their first
five post-fault cycles and are identified by topology exposure. No-fault RTOs
are not applicable. If no qualifying sequence exists by observation end, RTO
is right-censored. The main run-level RTO targets the first injected failure;
flapping raw events and packets support separate per-transition analyses.
No results are extrapolated to minutes per day.

Observed iperf3 JSON is retained and exported once into sealed
`iperf_intervals.csv` during run collection. Throughput reduction reads this
raw interval CSV; no throughput targets are substituted for observations.

iFogSim exports `tuples.csv` (tuple ID, application/module/device, simulated
execution start/finish and CPU duration), `placement.csv`, `sensor_emissions.csv`
and `device_resources.csv`. Compute summaries use tuple starts after warm-up.
The adapter uses seconds for CloudSim time, MI for work, MIPS for capacity,
bytes/second for simulated transmission capacity and W/J for power/energy.
Resource snapshots include a final energy flush. Energy is whole-simulation
energy, including warm-up, and is labeled `simulation_energy_j`.

iFogSim's queueing/scheduling and simplified tree network affect simulated
compute execution. These are not observed network latency, jitter, availability
or recovery. Upstream FogDevice's MIPS-sharing policy is retained and identified
by its pinned commit. No validated calibration to physical edge/fog/cloud
hardware is asserted. Tuple events are the compute counterpart of packet
records; fake Mininet-style packet observations are never created for iFogSim.
Each compute run includes an explicit `observation_schema.json` mapping these
counterparts, an SDN-controller-not-applicable event log, and an actual host/
process-tree `system_resources.csv` alongside simulated device resources.
