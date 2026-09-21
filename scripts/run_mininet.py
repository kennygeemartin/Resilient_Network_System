"""Run real Linux network namespaces and OVS. Never supplies synthetic results."""
import argparse
import csv
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from scripts.common import ROOT, config, dump, provenance, reserve_run, seal, wait_until
from scripts.matrix import matrix, realization, workload_hash, conditions
from scripts.model_loader import model

def join_csv(paths, output, fields=None):
    with Path(output).open('x',newline='') as target:
        writer = None
        for path in sorted(paths):
            with Path(path).open(newline='') as source:
                reader = csv.DictReader(source)
                if writer is None:
                    writer = csv.DictWriter(target,fieldnames=reader.fieldnames)
                    writer.writeheader()
                writer.writerows(reader)
        if writer is None and fields:
            csv.writer(target).writerow(fields)

def run(item, smoke=False):
    if sys.platform != 'linux' or os.geteuid() != 0:
        raise RuntimeError('Real Mininet requires root on the configured Ubuntu 22.04 host')
    from mininet.net import Mininet
    from mininet.node import OVSSwitch, RemoteController
    from mininet.link import TCLink, TCIntf
    from analysis.metrics import summarize_network
    c = config()
    class ConfiguredTCIntf(TCIntf):
        # Upstream 2.3.1b4 silently ignores rates above 1 Gbps. Explicitly
        # permit the declared rates, then verify installed kernel qdiscs.
        bwParamMax = max(link['bw_mbps'] for link in c['topology']['links'].values())
    real = realization(item['seed'],item,smoke)
    g = model.topology(c)
    rid = item['run_id']
    out = reserve_run('results/smoke/mininet' if smoke else 'results/raw/mininet',rid)
    work = ROOT / 'results/work' / rid
    work.mkdir(parents=True,exist_ok=False)
    meta = dict(item,tool='mininet',status='running',smoke=smoke,realization=real,
                workload_sha256=workload_hash(real),provenance=provenance(),
                clock='time.monotonic_ns; shared Linux kernel across namespaces',
                measurement='sensor -> forwarding service -> actuator; no simulated compute latency added',
                environment=json.loads((ROOT/'results/environment/environment_manifest.json').read_text()))
    dump(out/'metadata.json',meta)
    dump(out/'workload.json',real)
    sdn = item['architecture'] in ('A2','A3')
    net = Mininet(controller=None,switch=OVSSwitch,link=TCLink,build=False,autoSetMacs=False)
    processes, handles, controller = [], [], None
    relay_processes={}
    def launch(host, argv, logname):
        handle = (out/logname).open('xb')
        handles.append(handle)
        p = host.popen(argv,stdout=handle,stderr=subprocess.STDOUT,cwd=str(ROOT))
        processes.append(p)
        return p
    def spawn(host, mode, spec, name, script='udp.py'):
        specfile = work/(name+'.json')
        dump(specfile,spec)
        return launch(host,[sys.executable,str(ROOT/'mininet'/script),mode,str(specfile),str(out/(name+'.csv'))],name+'.log')
    def set_link(a,b,state):
        net.configLinkStatus(a,b,state)
        observations=[]
        for left,right in net[a].connectionsTo(net[b]):
            for intf in (left,right):
                value=json.loads(intf.node.cmd('ip','-j','link','show','dev',intf.name))
                if not value or ('UP' in value[0]['flags'])!=(state=='up'):
                    raise RuntimeError(f'Fault action did not set {intf.name} {state}')
                observations.append(dict(interface=intf.name,node=intf.node.name,state=value[0],observed_ns=time.monotonic_ns()))
        if not observations:
            raise RuntimeError(f'Fault target link absent: {a}/{b}')
        return observations
    try:
        if sdn:
            env = dict(os.environ,EXPERIMENT_ARCH=item['architecture'],EXPERIMENT_DIR=str(out),PYTHONPATH=str(ROOT))
            handle = (out/'controller_stdout.log').open('xb')
            handles.append(handle)
            controller = subprocess.Popen([sys.executable,'-m','scripts.controller_main'],
                env=env,cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT)
            net.addController('controller',controller=RemoteController,ip=c['controller']['listen_host'],port=c['controller']['port'])
        else:
            (out/'controller_events.jsonl').write_text(json.dumps({'event':'not_applicable','reason':'OVS RSTP conventional forwarding'})+'\n')
        for name,d in g.nodes(data=True):
            if d['switch']:
                net.addSwitch(name,dpid=f'{d["dpid"]:016x}',protocols='OpenFlow13',
                              failMode='secure' if sdn else 'standalone')
            else:
                net.addHost(name,ip=d['ip']+'/24',mac=d['mac'])
        for a,b,d in g.edges(data=True):
            # Explicit ports match the pure model and controller source bindings.
            net.addLink(a,b,port1=d['ports'][a] if g.nodes[a]['switch'] else 0,
                        port2=d['ports'][b] if g.nodes[b]['switch'] else 0,
                        bw=d['bw_mbps'],delay=f'{d["delay_ms"]}ms',max_queue_size=c['topology']['max_queue_packets'],
                        cls1=ConfiguredTCIntf,cls2=ConfiguredTCIntf)
        net.build()
        net.start()
        tc_state=[]
        for link in net.links:
            a,b=link.intf1.node.name,link.intf2.node.name
            expected=g[a][b]
            for intf in (link.intf1,link.intf2):
                classes=intf.node.cmd('tc','class','show','dev',intf.name)
                qdisc=intf.node.cmd('tc','qdisc','show','dev',intf.name)
                tc_state.append(dict(node=intf.node.name,interface=intf.name,classes=classes,qdisc=qdisc,expected_bw_mbps=expected['bw_mbps']))
                match=re.search(r'\brate ([\d.]+)([KMGT]?)bit',classes)
                if not match or abs(float(match[1])*1000**('KMGT'.index(match[2])+1 if match[2] else 0)/1e6-expected['bw_mbps'])>1:
                    raise RuntimeError(f'Kernel bandwidth configuration differs on {intf.name}: {classes}')
                delay=re.search(r'\bdelay ([\d.]+)(us|ms|s)',qdisc)
                if not delay or abs(float(delay[1])*{'us':.001,'ms':1,'s':1000}[delay[2]]-expected['delay_ms'])>0.001:
                    raise RuntimeError(f'Kernel delay configuration differs on {intf.name}: {qdisc}')
        dump(out/'tc_configuration.json',tc_state)
        for host in net.hosts:
            for name,d in g.nodes(data=True):
                if not d['switch'] and name!=host.name:
                    host.setARP(d['ip'],d['mac'])
        if sdn:
            until = time.monotonic()+c['timing']['setup_timeout_s']
            while not (out/'controller_ready').exists():
                if controller.poll() is not None or (out/'controller_error').exists() or time.monotonic()>until:
                    raise RuntimeError('Controller failed to install pipeline; inspect raw logs')
                time.sleep(.1)
        else:
            for switch in net.switches:
                subprocess.run(['ovs-vsctl','set','Bridge',switch.name,'rstp_enable=true'],check=True)
                subprocess.run(['ovs-ofctl','-O','OpenFlow13','add-flow',switch.name,'priority=0,actions=NORMAL'],check=True)
            # Convergence wait is outside the timed experiment, with actual state retained.
            time.sleep(10)
            with (out/'rstp_state.txt').open('x') as f:
                subprocess.run(['ovs-vsctl','--columns=name,rstp_status','list','Bridge'],stdout=f,check=True)
        start = time.monotonic_ns()+int(c['timing']['start_lead_s']*1e9)
        end = start+int(real['timing']['duration_s']*1e9)
        drain_end = end+int(c['timing']['drain_s']*1e9)
        meta.update(start_ns=start,end_ns=end,measurement_start_ns=start+int(real['timing']['warmup_s']*1e9))
        base = dict(run_id=rid,architecture=item['architecture'],scenario=item['scenario'],seed=item['seed'],end_ns=drain_end)
        actuators = {str(cell):g.nodes[f'c{cell}act']['ip'] for cell in range(1,5)}
        receivers = []
        for cell in range(1,5):
            spawn(net[f'c{cell}act'],'receive',dict(base,port=c['traffic']['actuator_port']),f'packets_c{cell}')
            receivers.append(out/f'packets_c{cell}.csv.ready')
        services = ['cloud'] if item['architecture']=='A0' else [f'c{k}fog' for k in range(1,5)]
        for host in services:
            relay_processes[host]=spawn(net[host],'relay',dict(base,port=c['traffic']['service_port'],actuators=actuators,
                  actuator_port=c['traffic']['actuator_port'],dscp={str(k):c['traffic'][f'C{k}']['dscp'] for k in range(3)}),'relay_'+host)
            receivers.append(out/f'relay_{host}.csv.ready')
        while not all(p.exists() for p in receivers):
            if time.monotonic_ns()>=start or any(p.poll() is not None for p in processes):
                raise RuntimeError('Receivers not ready before scheduled start')
            time.sleep(.01)
        for cell in range(1,5):
            for sensor in (1,2):
                idx = (cell-1)*2+sensor-1
                flows = []
                for cls in range(3):
                    tc = c['traffic'][f'C{cls}']
                    if cls == 1:
                        offsets = real['alarms_ns'][idx]
                    else:
                        period = real['period_ms'] if cls==0 else tc['period_ms']/real['load_multiplier']
                        offsets = list(range(real['flow_phase_ns'][idx],end-start,int(period*1e6)))
                    flows.append(dict(id=cell*100+sensor*10+cls,**{'class':cls},offsets_ns=offsets,
                                      bytes=tc['packet_bytes'],dscp=tc['dscp'],deadline_ns=int(tc['deadline_ms']*1e6)))
                destination = g.nodes['cloud' if item['architecture']=='A0' else f'c{cell}fog']['ip']
                spawn(net[f'c{cell}s{sensor}'],'send',dict(start_ns=start,destination=destination,
                    port=c['traffic']['service_port'],flows=flows),f'sent_c{cell}s{sensor}')
                port = c['traffic']['C3']['port']+cell*2+(sensor==2)
                launch(net['cloud'],['iperf3','-s','-1','-p',str(port),'--json'],f'iperf_server_c{cell}s{sensor}.json')
        resource_log = (out/'resource_stdout.log').open('xb')
        handles.append(resource_log)
        resource = subprocess.Popen([sys.executable,'-m','scripts.resources',str(out/'system_resources.csv'),str(os.getpid()),str(drain_end)],
                                     cwd=ROOT,stdout=resource_log,stderr=subprocess.STDOUT)
        processes.append(resource)
        if time.monotonic_ns()>=start:
            raise RuntimeError('Process/specification setup overran start lead; increase timing.start_lead_s')
        wait_until(start)
        for cell in range(1,5):
            for sensor in (1,2):
                port = c['traffic']['C3']['port']+cell*2+(sensor==2)
                rate = c['traffic']['C3']['background_mbps']*real['load_multiplier']
                launch(net[f'c{cell}s{sensor}'],['iperf3','-c',g.nodes['cloud']['ip'],'-p',str(port),'-t',str(real['timing']['duration_s']),
                      '--fq-rate',f'{rate}M','--dscp','0','--json'],f'iperf_client_c{cell}s{sensor}.json')
        meta['iperf_started_ns'] = start
        if item.get('attack'):
            wait_until(meta['measurement_start_ns'])
            perform_security(item,net,g,c,base,spawn,out)
        fault = item['fault']
        schedule = []
        if fault == 'link_flapping':
            schedule = [(s,i%2==0) for i,s in enumerate(c['faults']['flap_s'])]
        elif fault != 'none':
            schedule = [(real['timing']['fault_s'],True),(real['timing']['restore_s'],False)]
        with (out/'fault_events.jsonl').open('x',buffering=1) as f:
            for offset,down in schedule:
                wait_until(start+int(offset*1e9))
                before = time.monotonic_ns()
                state = 'down' if down else 'up'
                link_observations=[]
                service_observations=[]
                if fault in ('link_fail_stop','combined_failure','link_flapping'):
                    link_observations.extend(set_link(*real['fault_link'],state))
                if fault in ('fog_node_fail_stop','combined_failure'):
                    relay=relay_processes.get(f'c{real["fault_cell"]}fog')
                    if relay is not None:
                        import psutil
                        os.kill(relay.pid,signal.SIGSTOP if down else signal.SIGCONT)
                        deadline=time.monotonic()+2
                        while (psutil.Process(relay.pid).status()==psutil.STATUS_STOPPED)!=down:
                            if time.monotonic()>deadline:raise RuntimeError('Fog service stop/resume failed')
                            time.sleep(.001)
                        service_observations.append(dict(pid=relay.pid,state=psutil.Process(relay.pid).status(),observed_ns=time.monotonic_ns()))
                    link_observations.extend(set_link(f'c{real["fault_cell"]}fog',f'a{real["fault_cell"]}',state))
                after = time.monotonic_ns()
                f.write(json.dumps(dict(event='fault' if down else 'restore',fault=fault,
                    scheduled_ns=start+int(offset*1e9),command_start_ns=before,command_end_ns=after,monotonic_ns=before,
                    target_link=real['fault_link'],target_cell=real['fault_cell'],interfaces=link_observations,services=service_observations))+'\n')
        wait_until(drain_end)
        for p in processes:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.terminate()
                p.wait(timeout=5)
            if p.returncode != 0:
                raise RuntimeError(f'Child process failed ({p.returncode}); inspect raw logs')
        if (out/'controller_error').exists():
            raise RuntimeError('OpenFlow error recorded')
        join_csv(out.glob('packets_c*.csv'),out/'packets.csv')
        join_csv(out.glob('sent_c*.csv'),out/'sent.csv')
        from scripts.iperf_csv import export
        export(out)
        meta['status']='complete'
        dump(out/'metadata.json',meta)
        summary = summarize_network(out)
        summary.to_csv(out/'flow_summary.csv',index=False)
        summary[summary.traffic_class=='C0'][['flow_id','first_recovered_ns','rto_ms','rto_censored','rto_missing_reason']].to_csv(out/'derived_recovery_events.csv',index=False)
    except BaseException as e:
        meta.update(status='failed',error=repr(e))
        dump(out/'metadata.json',meta)
        raise
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    p.kill()
                    p.wait()
        try:
            if controller is not None:
                controller.terminate()
                try:
                    controller.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    controller.kill();controller.wait()
            net.stop()
        except Exception as e:
            meta.update(status='failed',cleanup_error=repr(e))
            dump(out/'metadata.json',meta)
            raise
        finally:
            for h in handles:
                h.close()
            seal(out)
    print(f'Completed {rid}: {out}')
    return out

def perform_security(item,net,g,c,base,spawn,out):
    port = c['traffic']['security_port']
    attack = item['attack']
    attacker, target = 'c1s2','c1act'
    if attack == 'east_west':
        target = 'c1s1'
    elif attack == 'cross_segment':
        target = 'c2act'
    elif attack == 'restricted_port':
        port += 1
    common = dict(count=c['traffic']['security_probes'],interval_ms=c['traffic']['security_probe_interval_ms'],end_ns=base['end_ns'])
    spawn(net[target],'receive',dict(common,port=port),'security_received_attack','security_probe.py')
    # Legitimate and attack probes share a receiver only when the same endpoint is used.
    shared = target=='c1act' and port==c['traffic']['security_port']
    if not shared:
        spawn(net['c1act'],'receive',dict(common,port=c['traffic']['security_port']),'security_received_legitimate','security_probe.py')
    time.sleep(.5)
    spec = dict(common,port=port,destination=g.nodes[target]['ip'],kind='attack',spoof=attack=='spoof_binding',
        interface=str(net[attacker].defaultIntf()),spoof_mac=g.nodes['c1s1']['mac'],spoof_ip=g.nodes['c1s1']['ip'],dst_mac=g.nodes[target]['mac'])
    spawn(net[attacker],'send',spec,'security_sent_attack','security_probe.py')
    spawn(net['c1s1'],'send',dict(common,port=c['traffic']['security_port'],destination=g.nodes['c1act']['ip'],kind='legitimate'),
          'security_sent_legitimate','security_probe.py')

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--smoke',action='store_true')
    p.add_argument('--security',action='store_true')
    p.add_argument('--supplemental',action='store_true')
    args = p.parse_args()
    from scripts.preflight import require_environment, require_gate
    require_environment()
    if args.smoke:
        condition = next(conditions())
        run(dict(phase=0,scenario=condition['scenario'],fault=condition['fault'],load='nominal',attack=None,
                 seed=1001,architecture='A3',run_id='smoke_1001_A3'),True)
    else:
        require_gate()
        for item in matrix(args.supplemental):
            if (item['phase'] in (3,4)) != args.security:
                continue
            existing = ROOT/'results/raw/mininet'/item['run_id']
            if existing.exists():
                from scripts.common import verify_seal
                verify_seal(existing)
                meta = json.loads((existing/'metadata.json').read_text())
                if meta['status']!='complete' or meta['provenance']['source_sha256']!=provenance()['source_sha256']:
                    raise RuntimeError(f'Cannot resume incompatible or failed run: {existing}')
                continue
            run(item)
