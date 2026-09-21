"""Compile against the pinned source and execute separate compute-placement runs."""
import argparse
import json
import os
import random
import subprocess
import sys
from scripts.common import ROOT, config, dump, provenance, reserve_run, seal
from scripts.matrix import seeds, realization, workload_hash

def classpath():
    return os.pathsep.join([str(ROOT/'build/ifogsim')]+[str(p) for p in sorted((ROOT/'third_party/ifogsim/jars').rglob('*.jar')) if 'sources' not in p.name])

def compile_java():
    build = ROOT/'build/ifogsim'
    build.mkdir(parents=True,exist_ok=True)
    subprocess.run(['javac','--release','11','-encoding','UTF-8','-cp',classpath(),'-sourcepath',str(ROOT/'third_party/ifogsim/src'),
                    '-d',str(build),str(ROOT/'ifogsim/ManufacturingExperiment.java')],check=True,cwd=ROOT)

def run(seed,architecture,load,smoke=False,development=False):
    import pandas as pd
    c = config()
    condition = dict(scenario='load_'+load,load=load)
    real = realization(seed,condition,smoke)
    base='results/development/ifogsim' if development else ('results/smoke/ifogsim' if smoke else 'results/raw/ifogsim')
    import time
    suffix=f'_{time.time_ns()}' if development else ''
    out = reserve_run(base,f'compute_{load}_{seed}_{architecture}'+suffix)
    compute = c['compute']
    duration = real['timing']['duration_s']
    props = dict(architecture=architecture,seed=seed,duration_s=duration,period_s=real['period_ms']/1000,
        min_event_s=compute['min_event_s'],resource_interval_s=compute['resource_interval_s'],
        module_ram_mb=compute['module_ram_mb'],module_mips=compute['module_mips'],module_size=compute['module_size_mb'],
        host_bw=compute['host_bw'],host_storage=compute['host_storage'],tuple_bytes=compute['tuple_bytes'],analytics_fraction=compute['analytics_fraction'])
    links = c['topology']['links']
    props.update(edge_bw=links['edge_access']['bw_mbps']*1e6/8,fog_bw=links['access_aggregation']['bw_mbps']*1e6/8,
        cloud_bw=links['core_cloud']['bw_mbps']*1e6/8,
        edge_fog_delay_s=(links['edge_access']['delay_ms']+links['fog_access']['delay_ms'])/1000,
        fog_cloud_delay_s=sum(links[k]['delay_ms'] for k in ('fog_access','access_aggregation','aggregation_core','core_cloud'))/1000)
    for profile,values in compute['profiles'].items():
        props.update({profile+'.'+k:v for k,v in values.items()})
    props.update({'cpu.'+k:v for k,v in compute['cpu_mi'].items()})
    for cell in range(1,5):
        for sensor in (1,2):
            idx = (cell-1)*2+sensor-1
            for cls in ('C0','C1','C2'):
                if cls=='C1':
                    offsets=real['alarms_ns'][idx]
                else:
                    period=real['period_ms'] if cls=='C0' else c['traffic']['C2']['period_ms']/real['load_multiplier']
                    offsets=range(real['flow_phase_ns'][idx],int(duration*1e9),int(period*1e6))
                props[f'schedule.{cell}.{sensor}.{cls}']=','.join(str(v/1e9) for v in offsets)
    (out/'input.properties').write_text('\n'.join(f'{k}={v}' for k,v in sorted(props.items()))+'\n')
    meta=dict(tool='ifogsim',run_id=out.name,seed=seed,architecture=architecture,scenario=condition['scenario'],load=load,
              smoke=smoke,development_only=development,status='running',workload_sha256=workload_hash(real),realization=real,provenance=provenance(),
              environment=json.loads((ROOT/'results/environment/environment_manifest.json').read_text()),
              fault='not_applied_compute_placement_study',units='SI seconds/MI/MIPS/bytes/W/J')
    dump(out/'metadata.json',meta)
    dump(out/'observation_schema.json',dict(tool='ifogsim',packet_level_equivalent='tuples.csv',
         flow_summary_equivalent='compute_summary.csv',network_measurements=False))
    (out/'controller_events.jsonl').write_text(json.dumps(dict(event='not_applicable',
         reason='Compute placement simulation; no SDN controller observations',placement_trace='placement.csv'))+'\n')
    monitor_log=(out/'resource_stdout.log').open('x')
    monitor=subprocess.Popen([sys.executable,'-m','scripts.resources',str(out/'system_resources.csv'),str(os.getpid()),
        str(time.monotonic_ns()+int(compute['max_walltime_s']*1e9)),
        '--stop-file',str(out/'resource_stop')],cwd=ROOT,stdout=monitor_log,stderr=subprocess.STDOUT)
    try:
        ready_deadline=time.monotonic()+10
        while not (out/'system_resources.csv.ready').exists():
            if monitor.poll() is not None or time.monotonic()>ready_deadline:
                raise RuntimeError('Compute system resource monitor failed to start')
            time.sleep(.01)
        with (out/'stdout.log').open('x') as log:
            subprocess.run(['java','-cp',classpath(),'ManufacturingExperiment',str(out/'input.properties'),str(out)],
                stdout=log,stderr=subprocess.STDOUT,check=True,cwd=ROOT,timeout=compute['max_walltime_s'])
        tuples = pd.read_csv(out/'tuples.csv')
        if tuples.empty:
            raise RuntimeError('No completed compute tuples')
        measured=tuples[(tuples.start_s>=real['timing']['warmup_s'])&(tuples.finish_s<=duration)]
        measured.groupby(['module','device']).agg(completed=('tuple_id','count'),mean_cpu_s=('cpu_s','mean')).reset_index().to_csv(out/'compute_summary.csv',index=False)
        meta['status']='complete'
    except BaseException as e:
        meta.update(status='failed',error=repr(e))
        raise
    finally:
        (out/'resource_stop').write_text(str(time.monotonic_ns())+'\n')
        try:
            monitor.wait(timeout=5)
        except subprocess.TimeoutExpired:
            monitor.kill();monitor.wait()
        monitor_log.close()
        if monitor.returncode!=0:
            meta.update(status='failed',resource_error='resource monitor failed')
        dump(out/'metadata.json',meta)
        seal(out)
    if meta['status']!='complete':
        raise RuntimeError(f'Compute run failed: {out}')
    return out

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--compile-only',action='store_true')
    p.add_argument('--smoke',action='store_true')
    p.add_argument('--development-smoke',action='store_true',help='Non-publication diagnostic on a non-target platform; cannot satisfy the gate')
    args = p.parse_args()
    if not args.compile_only and not args.development_smoke:
        from scripts.preflight import require_environment, require_gate
        require_environment()
        if not args.smoke:
            require_gate()
    compile_java()
    if not args.compile_only:
        if args.development_smoke:
            from scripts.capture_environment import capture
            capture()
            for architecture in config()['architectures']:
                print(run(1001,architecture,'nominal',True,True),flush=True)
        elif args.smoke:
            run(1001,'A3','nominal',True)
        else:
            for seed in seeds():
                for load in config()['loads']:
                    order = list(config()['architectures'])
                    random.Random(f'compute-order:{seed}:{load}').shuffle(order)
                    for architecture in order:
                        existing = ROOT/'results/raw/ifogsim'/f'compute_{load}_{seed}_{architecture}'
                        if existing.exists():
                            from scripts.common import verify_seal
                            verify_seal(existing)
                            meta=json.loads((existing/'metadata.json').read_text())
                            if meta['status']!='complete' or meta['provenance']['source_sha256']!=provenance()['source_sha256']:
                                raise RuntimeError(f'Incompatible prior run: {existing}')
                            continue
                        run(seed,architecture,load)
