import json
import pandas as pd
from scripts.common import ROOT, dump, digest, verify_seal
from analysis.metrics import network_run_metrics
from analysis.statistics import describe, compare

NETWORK_METRICS=['latency_ms','jitter_ms','tcp_throughput_mbps','udp_throughput_mbps','availability',
    'loss_fraction','mean_flow_outage_s','total_outage_s','summed_flow_outage_s','rto_ms','detection_ms','controller_reaction_ms',
    'scheduler_miss_fraction','attack_block_rate','authorized_allow_rate','false_block_rate']

def process():
    from scripts.verify_results import verify_raw
    verify_raw()
    rows=[]
    provenance={}
    for path in sorted((ROOT/'results/raw/mininet').iterdir()):
        verify_seal(path)
        provenance[path.relative_to(ROOT).as_posix()]=digest(path/'SHA256SUMS.json')
        result=network_run_metrics(path)
        for metric in NETWORK_METRICS:
            if metric not in result:
                continue
            value=result[metric]
            reason=''
            if value is None or pd.isna(value):
                reason=result.get(metric.replace('_ms','')+'_reason','no_received_or_consecutive_packets')
            rows.append({k:result[k] for k in ('tool','run_id','scenario','phase','load','architecture','seed')} |
                        dict(metric=metric,value=value,missing_reason=reason))
    for path in sorted((ROOT/'results/raw/ifogsim').iterdir()):
        verify_seal(path)
        provenance[path.relative_to(ROOT).as_posix()]=digest(path/'SHA256SUMS.json')
        meta=json.loads((path/'metadata.json').read_text())
        t=pd.read_csv(path/'tuples.csv')
        warmup=meta['realization']['timing']['warmup_s']
        duration=meta['realization']['timing']['duration_s']
        t=t[(t.start_s>=warmup)&(t.finish_s<=duration)]
        resources=pd.read_csv(path/'device_resources.csv')
        result={'mean_tuple_cpu_s':float(t.cpu_s.mean()),'completed_tuples':len(t)}
        # Compute energy is a simulator observation, integrated by iFogSim.
        last=resources.sort_values('simulation_s').groupby('device').tail(1)
        result['simulation_energy_j']=float(last.energy_j.sum())
        for metric,value in result.items():
            rows.append({k:meta[k] for k in ('tool','run_id','scenario','load','architecture','seed')} |
                        dict(phase='compute',metric=metric,value=value,missing_reason=''))
    long=pd.DataFrame(rows)
    long.to_csv(ROOT/'results/processed/run_metrics.csv',index=False)
    summaries=[]
    for key,frame in long.groupby(['tool','scenario','load','architecture','metric']):
        summaries.append(dict(zip(['tool','scenario','load','architecture','metric'],key)) |
                         dict(n_scheduled=len(frame),n_missing=int(frame.value.isna().sum()),**describe(frame.value)))
    pd.DataFrame(summaries).to_csv(ROOT/'results/statistics/descriptive.csv',index=False)
    pairs,omnibus=compare(long)
    pairs.to_csv(ROOT/'results/statistics/paired.csv',index=False)
    omnibus.to_csv(ROOT/'results/statistics/omnibus.csv',index=False)
    # Security overhead uses paired within-seed A3-A2 differences, not independent CIs.
    overhead=[]
    for (scenario,metric),frame in long[(long.tool=='mininet') & long.scenario.str.startswith('overhead_')].groupby(['scenario','metric']):
        wide=frame.pivot(index='seed',columns='architecture',values='value').dropna()
        if len(wide):
            overhead.append(dict(scenario=scenario,metric=metric,**describe(wide.A3-wide.A2)))
    pd.DataFrame(overhead).to_csv(ROOT/'results/statistics/security_overhead.csv',index=False)
    dump(ROOT/'results/processed/provenance.json',provenance)
    print(f'Processed {len(provenance)} immutable runs; {len(long)} seed-level metrics')

if __name__=='__main__':
    process()
