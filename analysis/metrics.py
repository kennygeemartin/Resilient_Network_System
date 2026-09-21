"""Run/flow estimands from raw observations; lost packets remain in denominators."""
import json
import numpy as np
import pandas as pd

def events(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

def first_recovery(cycles, fault_ns):
    count = 0
    first = None
    previous = None
    for row in cycles[cycles.scheduled_ns >= fault_ns].sort_values('sequence').itertuples():
        if row.success and (previous is None or row.sequence==previous+1):
            count += 1
        elif row.success:
            count = 1
        else:
            count = 0
        if count==1:
            first = int(row.receive_ns)
        if count>=5:
            return (first-fault_ns)/1e6, first
        previous = row.sequence
    return None, None

def read_cycles(path):
    meta = json.loads((path/'metadata.json').read_text())
    sent = pd.read_csv(path/'sent.csv')
    packets = pd.read_csv(path/'packets.csv')
    if sent.duplicated(['flow_id','sequence']).any():
        raise ValueError('Duplicate scheduled cycle')
    if len(packets) and ((packets.latency_ns<0).any() or (packets.receive_ns<packets.send_ns).any()):
        raise ValueError('Invalid clock order')
    received = packets.sort_values('receive_ns').drop_duplicates(['flow_id','sequence'])
    cols = ['flow_id','sequence','receive_ns','latency_ns','deadline_ns','deadline_missed']
    cycles = sent.merge(received[cols],on=['flow_id','sequence'],how='left',validate='one_to_one')
    cycles['success'] = cycles.receive_ns.notna() & cycles.deadline_missed.eq(0)
    cycles['received'] = cycles.receive_ns.notna()
    cycles = cycles[(cycles.scheduled_ns>=meta['measurement_start_ns']) & (cycles.scheduled_ns<meta['end_ns'])].copy()
    return meta,cycles,packets

def summarize_network(path):
    meta,cycles,_ = read_cycles(path)
    faults = [e for e in events(path/'fault_events.jsonl') if e['event']=='fault']
    fault_ns = faults[0]['monotonic_ns'] if faults else None
    rows = []
    for (flow,cls), group in cycles.groupby(['flow_id','class']):
        group = group.sort_values('sequence')
        lat = group.loc[group.received,'latency_ns']/1e6
        # RFC-style adjacent packet delay variation, using consecutive received sequences only.
        adjacent = group[group.received].copy()
        diffs = adjacent.latency_ns.diff().abs()[adjacent.sequence.diff().eq(1)]/1e6
        duration = (meta['end_ns']-meta['measurement_start_ns'])/1e9
        rto,first = first_recovery(group,fault_ns) if cls=='C0' and faults else (None,None)
        next_ns = group.scheduled_ns.shift(-1).fillna(meta['end_ns'])
        outage = float(((next_ns-group.scheduled_ns).clip(lower=0)*~group.success).sum()/1e9) if cls=='C0' else None
        rows.append(dict(tool='mininet',run_id=meta['run_id'],architecture=meta['architecture'],
            scenario=meta['scenario'],phase=meta['phase'],load=meta['load'],seed=meta['seed'],flow_id=flow,
            traffic_class=cls,scheduled=len(group),sent=int(group.status.eq('sent').sum()),
            received=int(group.received.sum()),successful=int(group.success.sum()),
            scheduler_misses=int(group.status.eq('scheduler_miss').sum()),
            latency_ms=float(lat.mean()) if len(lat) else None,
            jitter_ms=float(diffs.mean()) if len(diffs) else None,
            throughput_mbps=float(group.loc[group.received,'packet_bytes'].sum()*8/duration/1e6),
            loss_fraction=float(1-group.received.mean()),availability=float(group.success.mean()),
            outage_s=outage,rto_ms=rto,rto_censored=bool(cls=='C0' and faults and rto is None),
            first_recovered_ns=first,latency_missing_reason='no_received_packets' if not len(lat) else '',
            jitter_missing_reason='no_consecutive_received_pairs' if not len(diffs) else '',
            rto_missing_reason=('no_fault_or_not_critical' if not (faults and cls=='C0') else 'right_censored') if rto is None else ''))
    return pd.DataFrame(rows)

def network_run_metrics(path):
    meta,cycles,_ = read_cycles(path)
    summary = summarize_network(path)
    critical = cycles[cycles['class']=='C0']
    cs = summary[summary.traffic_class=='C0']
    observed = critical.loc[critical.received,'latency_ns']/1e6
    result = dict(tool='mininet',run_id=meta['run_id'],scenario=meta['scenario'],phase=meta['phase'],
                  load=meta['load'],architecture=meta['architecture'],seed=meta['seed'],
                  latency_ms=observed.mean() if len(observed) else None,
                  availability=float(critical.success.mean()),loss_fraction=float(1-critical.received.mean()),
                  jitter_ms=cs.jitter_ms.mean() if cs.jitter_ms.notna().any() else None,
                  udp_throughput_mbps=summary.throughput_mbps.sum(),
                  mean_flow_outage_s=cs.outage_s.mean(),scheduler_miss_fraction=float(critical.status.eq('scheduler_miss').mean()))
    intervals=[]
    for _,flow in critical.groupby('flow_id'):
        flow=flow.sort_values('scheduled_ns')
        next_ns=flow.scheduled_ns.shift(-1).fillna(meta['end_ns'])
        intervals.extend((int(a),int(b)) for a,b,ok in zip(flow.scheduled_ns,next_ns,flow.success) if not ok)
    union=[]
    for a,b in sorted(intervals):
        if union and a<=union[-1][1]:
            union[-1]=(union[-1][0],max(b,union[-1][1]))
        else:
            union.append((a,b))
    result['total_outage_s']=sum(b-a for a,b in union)/1e9
    result['summed_flow_outage_s']=float(cs.outage_s.sum())
    # RTO is reported on the preselected fault cell's critical flows, including
    # unaffected paths. Never select a flow after inspecting performance.
    target = cs[cs.flow_id.floordiv(100).eq(meta['realization']['fault_cell'])]
    result['rto_ms'] = target.rto_ms.max() if target.rto_ms.notna().all() else None
    result['rto_censored'] = bool(target.rto_censored.any())
    result['rto_reason'] = 'right_censored' if result['rto_censored'] else ('no_fault' if meta['fault']=='none' else '')
    fault_events = [e for e in events(path/'fault_events.jsonl') if e['event']=='fault']
    control_events = events(path/'controller_events.jsonl')
    if fault_events and meta['architecture'] in ('A2','A3'):
        fault = fault_events[0]
        graph = __import__('scripts.model_loader',fromlist=['model']).model.topology(__import__('scripts.common',fromlist=['config']).config())
        pairs = [(f'c{fault["target_cell"]}fog',f'a{fault["target_cell"]}')] if meta['fault']=='fog_node_fail_stop' else [tuple(fault['target_link'])]
        watched = {(graph.nodes[n]['dpid'],graph[a][b]['ports'][n]) for a,b in pairs for n in (a,b) if graph.nodes[n]['switch']}
        detections = [e['monotonic_ns'] for e in control_events if e['event']=='port_status' and
                      (e['dpid'],e['port']) in watched and e['state']&1 and e['monotonic_ns']>=fault['command_start_ns']]
        # Detection can precede command completion: reference command start and
        # retain the [start,end] fault-action interval rather than clipping negatives.
        result['detection_ms'] = (min(detections)-fault['command_start_ns'])/1e6 if detections else None
        result['detection_reason'] = '' if detections else 'no_matching_port_status'
    else:
        result['detection_ms'] = None
        result['detection_reason'] = 'no_fault_or_conventional_forwarding'
    result['controller_reaction_ms'] = None
    result['controller_reaction_reason'] = 'proactive_fast_failover_no_reactive_flow_mod'
    throughput = 0.0
    warmup = meta['realization']['timing']['warmup_s']
    duration = meta['realization']['timing']['duration_s']
    iperf=pd.read_csv(path/'iperf_intervals.csv')
    if iperf.stream.nunique()!=8 or iperf.isna().any().any():
        raise ValueError('Incomplete iperf interval observations')
    for stream,frame in iperf.groupby('stream'):
        intervals=frame[(frame.start_s>=warmup)&(frame.end_s<=duration)&~frame.omitted]
        if intervals.empty or (intervals.seconds<=0).any():
            raise ValueError(f'No measured iperf intervals: {stream}')
        throughput += intervals['bytes'].sum()*8/intervals.seconds.sum()/1e6
    result['tcp_throughput_mbps'] = throughput
    if meta.get('attack'):
        sent = pd.concat(pd.read_csv(p) for p in path.glob('security_sent_*.csv'))
        rx = pd.concat(pd.read_csv(p) for p in path.glob('security_received_*.csv')).drop_duplicates(['probe_id','kind'])
        for kind in ('attack','legitimate'):
            count = sent[sent.kind==kind].probe_id.nunique()
            received = rx[rx.kind==kind].probe_id.nunique()
            if not count or received>count:
                raise ValueError('Invalid security denominator')
            result['attack_block_rate' if kind=='attack' else 'authorized_allow_rate'] = (1-received/count) if kind=='attack' else received/count
        result['false_block_rate'] = 1-result['authorized_allow_rate']
    return result
