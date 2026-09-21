"""Strict full-matrix validation, paired realizations and packet reconciliation."""
import argparse
import json
import numpy as np
import pandas as pd
from scripts.common import ROOT,config,digest,verify_seal
from scripts.matrix import matrix,seeds,realization,workload_hash
from analysis.metrics import summarize_network,read_cycles

def require(condition,message):
    if not condition:
        raise ValueError(message)

def verify_network(path,item):
    verify_seal(path)
    meta=json.loads((path/'metadata.json').read_text())
    for key in ('tool','run_id','architecture','scenario','seed','start_ns','end_ns','measurement_start_ns',
                'status','smoke','realization','workload_sha256','environment','provenance','fault','load'):
        require(key in meta,f'{path}: missing metadata {key}')
    require(meta['status']=='complete' and not meta['smoke'],f'{path}: failed or smoke run in publication results')
    for key in ('run_id','architecture','scenario','seed','fault','load'):
        require(meta[key]==item[key],f'{path}: matrix mismatch in {key}')
    require(meta['environment']['ready'],f'{path}: incompatible experiment environment')
    expected_real=realization(item['seed'],item)
    require(meta['realization']==expected_real,f'{path}: stochastic realization differs from preregistered design')
    require(meta['workload_sha256']==workload_hash(expected_real),f'{path}: workload hash mismatch')
    for name in ('packets.csv','sent.csv','flow_summary.csv','controller_events.jsonl','fault_events.jsonl','system_resources.csv','tc_configuration.json','derived_recovery_events.csv','iperf_intervals.csv'):
        require((path/name).exists(),f'{path}: missing {name}')
    _,cycles,packets=read_cycles(path)
    sent=pd.read_csv(path/'sent.csv')
    require(set(sent.status)<= {'sent','scheduler_miss','send_error'},f'{path}: invalid sender status')
    require(not sent[['flow_id','class','sequence','scheduled_ns','packet_bytes','status']].isna().any().any(),f'{path}: missing scheduled cycle fields')
    expected_ids={cell*100+sensor*10+cls for cell in range(1,5) for sensor in (1,2) for cls in range(3)}
    require(set(sent.flow_id)==expected_ids,f'{path}: missing traffic flow')
    duration=int(meta['realization']['timing']['duration_s']*1e9)
    for cell in range(1,5):
        for sensor in (1,2):
            idx=(cell-1)*2+sensor-1
            for cls in range(3):
                if cls==1:
                    offsets=expected_real['alarms_ns'][idx]
                else:
                    interval=expected_real['period_ms'] if cls==0 else config()['traffic']['C2']['period_ms']/expected_real['load_multiplier']
                    offsets=list(range(expected_real['flow_phase_ns'][idx],duration,int(interval*1e6)))
                sub=sent[sent.flow_id==cell*100+sensor*10+cls].sort_values('sequence')
                require(len(sub)==len(offsets),f'{path}: scheduled packet count differs from workload')
                require(np.array_equal(sub.sequence.to_numpy(),np.arange(len(offsets))),f'{path}: missing/reordered sequence ledger')
                require(np.array_equal(sub.scheduled_ns.to_numpy()-meta['start_ns'],np.asarray(offsets)),f'{path}: schedule mismatch')
    if len(packets):
        require(not packets.isna().any().any(),f'{path}: NaNs in packet observations')
        for field in ('run_id','architecture','scenario','seed'):
            require(packets[field].eq(meta[field]).all(),f'{path}: packet {field} differs from metadata')
        require((packets.latency_ns==packets.receive_ns-packets.send_ns).all(),f'{path}: packet latency mismatch')
        require((packets.deadline_missed==((packets.receive_ns-packets.scheduled_ns)>packets.deadline_ns).astype(int)).all(),f'{path}: deadline flag mismatch')
        keys=set(zip(sent.loc[sent.status=='sent','flow_id'],sent.loc[sent.status=='sent','sequence']))
        require(set(zip(packets.flow_id,packets.sequence))<=keys,f'{path}: received unscheduled/unsent packets')
    actual=pd.read_csv(path/'flow_summary.csv').sort_values('flow_id').reset_index(drop=True)
    expected=summarize_network(path).sort_values('flow_id').reset_index(drop=True)
    for col in ('latency_missing_reason','jitter_missing_reason','rto_missing_reason'):
        actual[col]=actual[col].fillna('')
    pd.testing.assert_frame_equal(actual,expected,check_dtype=False,check_exact=False,rtol=1e-10,atol=1e-9)
    required=['scheduled','sent','received','successful','throughput_mbps','loss_fraction','availability','scheduler_misses']
    require(not actual[required].isna().any().any(),f'{path}: unexpected summary NaNs')
    require((actual.successful<=actual.received).all() and (actual.received<=actual.sent).all(),f'{path}: inconsistent count hierarchy')
    require(actual.scheduled.sum()==len(cycles),f'{path}: raw/summary counts disagree')
    for field,reason in [('latency_ms','latency_missing_reason'),('jitter_ms','jitter_missing_reason'),('rto_ms','rto_missing_reason')]:
        require(actual.loc[actual[field].isna(),reason].fillna('').ne('').all(),f'{path}: unexplained {field} NaNs')
    require(len(pd.read_csv(path/'system_resources.csv'))>0,f'{path}: empty resource log')
    tc=json.loads((path/'tc_configuration.json').read_text())
    require(len(tc)==54,f'{path}: missing configured interface evidence')
    from analysis.metrics import events
    faults=events(path/'fault_events.jsonl')
    expected_events=0 if item['fault']=='none' else (6 if item['fault']=='link_flapping' else 2)
    require(len(faults)==expected_events,f'{path}: missing fault/restore events')
    for event in faults:
        require(event['command_end_ns']>=event['command_start_ns'],f'{path}: invalid fault interval')
        require(bool(event['interfaces']),f'{path}: missing actual fault state')
    controller=events(path/'controller_events.jsonl')
    require(not any(e['event']=='openflow_error' for e in controller),f'{path}: OpenFlow errors')
    if item['architecture'] in ('A2','A3'):
        require(any(e['event']=='ready' for e in controller),f'{path}: controller never ready')
    from analysis.metrics import network_run_metrics
    network_run_metrics(path)  # Validate iperf/security observations too.
    return meta

def verify_raw():
    seedset=set(seeds())
    require(len(seedset)>=30,'Fewer than 30 independent seeds')
    expected=list(matrix())
    network=ROOT/'results/raw/mininet'
    require(network.exists(),'No Mininet raw experiment data. Run the Ubuntu preflight and experiment first.')
    present={p.name for p in network.iterdir() if p.is_dir()}
    missing={r['run_id'] for r in expected}-present
    require(not missing,f'Missing {len(missing)} Mininet runs, e.g. {sorted(missing)[:3]}')
    extras=present-{r['run_id'] for r in expected}
    if extras:
        supplemental=[r for r in matrix(True) if r['phase']==5]
        allowed={r['run_id'] for r in supplemental}
        require(extras==allowed,'Unknown or incomplete supplemental run matrix')
        expected.extend(supplemental)
    metadata=[]
    for item in expected:
        metadata.append(verify_network(network/item['run_id'],item))
    frame=pd.DataFrame(metadata)
    require(frame.provenance.map(lambda p:p['source_sha256']).nunique()==1,'Mixed source revisions in one campaign')
    for scenario,group in frame.groupby('scenario'):
        for arch,part in group.groupby('architecture'):
            require(set(part.seed)==seedset,f'Seed sets differ: {scenario}/{arch}')
        require(group.groupby('seed').workload_sha256.nunique().eq(1).all(),f'Unpaired workloads: {scenario}')
    compute=ROOT/'results/raw/ifogsim'
    for seed in seedset:
        for load in config()['loads']:
            reference=None
            placement_reference=None
            for arch in config()['architectures']:
                path=compute/f'compute_{load}_{seed}_{arch}'
                require(path.exists(),f'Missing iFogSim run: {path.name}')
                verify_seal(path)
                for name in ('tuples.csv','compute_summary.csv','controller_events.jsonl','system_resources.csv','observation_schema.json'):
                    require((path/name).exists(),f'{path}: missing compute observation {name}')
                meta=json.loads((path/'metadata.json').read_text())
                require(meta['status']=='complete' and not meta['smoke'] and meta['tool']=='ifogsim',f'{path}: invalid compute metadata')
                require(meta['seed']==seed and meta['architecture']==arch and meta['load']==load,f'{path}: compute matrix mismatch')
                require(meta['environment']['ready'],f'{path}: incompatible compute environment')
                require(meta['provenance']['source_sha256']==frame.iloc[0].provenance['source_sha256'],f'{path}: mixed source revision')
                require(meta['workload_sha256']==workload_hash(realization(seed,dict(scenario='load_'+load,load=load))),f'{path}: compute workload mismatch')
                require(reference is None or meta['workload_sha256']==reference,f'{path}: unpaired compute workload')
                reference=meta['workload_sha256']
                placement=pd.read_csv(path/'placement.csv').sort_values('module').reset_index(drop=True)
                require(len(placement)==20,f'{path}: missing modules')
                for row in placement.itertuples():
                    cell=int(row.module[-1])
                    base=row.module[:-1]
                    require(base in ('Ingest','Filter','Control','Analytics','Storage') and 1<=cell<=4,f'{path}: unknown module')
                    intended='cloud' if arch=='A0' or base in ('Analytics','Storage') else f'fog{cell}'
                    require(row.device==intended,f'{path}: incorrect placement for {row.module}')
                if arch!='A0':
                    if placement_reference is not None:
                        pd.testing.assert_frame_equal(placement,placement_reference)
                    placement_reference=placement
                tuples=pd.read_csv(path/'tuples.csv')
                require(not tuples.empty and not tuples.isna().any().any(),f'{path}: invalid compute observations')
                require((tuples.cpu_s>=0).all() and (tuples.finish_s>=tuples.start_s).all(),f'{path}: invalid compute duration')
                measured=tuples[(tuples.start_s>=meta['realization']['timing']['warmup_s'])&
                                (tuples.finish_s<=meta['realization']['timing']['duration_s'])]
                summary=pd.read_csv(path/'compute_summary.csv')
                require(summary.completed.sum()==len(measured),f'{path}: compute counts disagree')
    print(f'PASS: {len(expected)} network and {len(seedset)*len(config()["loads"])*4} compute runs')

def verify_processed():
    long=pd.read_csv(ROOT/'results/processed/run_metrics.csv')
    require(not long.drop(columns=['value','missing_reason']).isna().any().any(),'Missing metric identifiers')
    require(long.loc[long.value.isna(),'missing_reason'].fillna('').ne('').all(),'Unexpected processed NaNs')
    require(np.isfinite(long.value.dropna()).all(),'Infinite processed metrics')
    manifest=json.loads((ROOT/'results/processed/provenance.json').read_text())
    for path,sha in manifest.items():
        require(digest(ROOT/path/'SHA256SUMS.json')==sha,'Stale processed data')
    from analysis.statistics import describe
    statistics=pd.read_csv(ROOT/'results/statistics/descriptive.csv')
    for key,frame in long.groupby(['tool','scenario','load','architecture','metric']):
        target=statistics
        for field,value in zip(['tool','scenario','load','architecture','metric'],key):
            target=target[target[field]==value]
        require(len(target)==1,'Missing/duplicate descriptive statistic')
        for field,value in describe(frame.value).items():
            got=target.iloc[0][field]
            require(pd.isna(got) if value is None else np.isclose(got,value),f'Statistics disagree with processed data: {key}/{field}')
    pairs=pd.read_csv(ROOT/'results/statistics/paired.csv')
    omnibus=pd.read_csv(ROOT/'results/statistics/omnibus.csv')
    for table,fields in [(pairs,['n','p','p_holm','statistic','difference_b_minus_a','rank_biserial','normality_p']),
                         (omnibus,['n','p','statistic','effect_size','sphericity_p','normality_p'])]:
        require(np.isfinite(table[fields].to_numpy(dtype=float)).all(),'Unexpected NaNs/infinities in inferential statistics')
    require(pairs.loc[pairs.dz.isna(),'dz_reason'].fillna('').ne('').all(),'Unexplained undefined effect size')
    require((ROOT/'figures/provenance.json').exists(),'Figures missing')
    require((ROOT/'tables/provenance.json').exists(),'Tables missing')
    figure_manifest=json.loads((ROOT/'figures/provenance.json').read_text())
    require(figure_manifest['descriptive_sha256']==digest(ROOT/'results/statistics/descriptive.csv'),'Stale figures')
    require(figure_manifest['overhead_sha256']==digest(ROOT/'results/statistics/security_overhead.csv'),'Stale overhead figure')
    require(figure_manifest['raw_manifest_sha256']==digest(ROOT/'results/processed/provenance.json'),'Stale figure raw provenance')
    for name in ('latency','throughput_load','availability','rto_failures','security_overhead','attack_block_rate','authorized_allow_rate','false_block_rate'):
        require((ROOT/f'figures/{name}.pdf').exists(),f'Missing figure: {name}')
    for name in ('descriptive','paired','omnibus','security_overhead'):
        pd.testing.assert_frame_equal(pd.read_csv(ROOT/f'tables/{name}.csv'),pd.read_csv(ROOT/f'results/statistics/{name}.csv'))

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--raw-only',action='store_true')
    args=p.parse_args()
    from scripts.audit_constants import audit
    audit();verify_raw()
    if not args.raw_only:
        verify_processed()
