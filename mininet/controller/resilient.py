"""OS-Ken OF1.3 pipeline with source-path VLANs and ingress fast failover.

The VLAN identifies a precomputed path. Intermediate hops never independently
choose a reverse backup, avoiding forwarding loops. Only access-g1 links are
faulted: both forward and return entries watch that port at the adjacent switch.
No general arbitrary-link protection or application migration is claimed.
"""
import json
import os
import time
from pathlib import Path
from os_ken.base import app_manager
from os_ken.controller import ofp_event
from os_ken.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER, set_ev_cls
from os_ken.ofproto import ofproto_v1_3
from scripts.common import config
from scripts.model_loader import model

class ResilientController(app_manager.OSKenApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.c = config()
        self.graph = model.topology(self.c)
        self.switches = model.switch_graph(self.graph)
        self.arch = os.environ['EXPERIMENT_ARCH']
        self.directory = Path(os.environ['EXPERIMENT_DIR'])
        self.log = (self.directory / 'controller_events.jsonl').open('x', buffering=1)
        self.datapaths = {}
        self.ready = set()
        self.pending = {}

    def event(self, event, **extra):
        self.log.write(json.dumps(dict(event=event, monotonic_ns=time.monotonic_ns(), **extra))+'\n')

    def flow(self, dp, table, priority, match, actions=None, goto=None):
        p, o = dp.ofproto_parser, dp.ofproto
        inst = []
        if actions:
            inst.append(p.OFPInstructionActions(o.OFPIT_APPLY_ACTIONS, actions))
        if goto is not None:
            inst.append(p.OFPInstructionGotoTable(goto))
        dp.send_msg(p.OFPFlowMod(datapath=dp, table_id=table, priority=priority,
                               match=p.OFPMatch(**match), instructions=inst))
        self.event('flow_mod_sent',dpid=dp.id,table=table,priority=priority,phase='preinstalled')

    def output(self, dp, switch, neighbor):
        return dp.ofproto_parser.OFPActionOutput(self.graph[switch][neighbor]['ports'][switch])

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def connected(self, ev):
        dp = ev.msg.datapath
        # The native-thread hub can deliver the observer event before the
        # transport handler assigns dp.id. The feature reply is authoritative.
        dp.id = ev.msg.datapath_id
        self.datapaths[dp.id] = dp
        if len(self.datapaths) == 7:
            self.install()

    def install(self):
        for switch, attrs in self.switches.nodes(data=True):
            dp = self.datapaths[attrs['dpid']]
            p, o = dp.ofproto_parser, dp.ofproto
            # Misses drop in all three tables.
            for t in range(3):
                self.flow(dp, t, 0, {})
            for neighbor in self.graph[switch]:
                port = self.graph[switch][neighbor]['ports'][switch]
                host = self.graph.nodes[neighbor]
                if host['switch']:
                    self.flow(dp, 0, 100, {'in_port':port}, goto=1)
                    continue
                match = dict(in_port=port, eth_type=0x0800, vlan_vid=o.OFPVID_NONE)
                if self.arch == 'A3':
                    match.update(eth_src=host['mac'], ipv4_src=host['ip'])
                # Classification is visible through per-DSCP rule counters.
                for cls in ('C0','C1','C2','C3'):
                    self.flow(dp, 0, 200, dict(match,ip_dscp=self.c['traffic'][cls]['dscp']), goto=1)
                self.flow(dp, 0, 100, match, goto=1)
            if self.arch == 'A2':
                self.flow(dp, 1, 1, {'eth_type':0x0800}, goto=2)
            else:
                for rule in model.rules(self.c, self.arch):
                    match = dict(eth_type=0x0800, ipv4_src=self.graph.nodes[rule['src']]['ip'],
                                 ipv4_dst=self.graph.nodes[rule['dst']]['ip'], ip_proto=rule['protocol'])
                    field = ('udp_' if rule['protocol']==17 else 'tcp_')
                    match[field + ('dst' if 'port' in rule else 'src')] = rule.get('port', rule.get('source_port'))
                    self.flow(dp, 1, 100, match, goto=2)
        hosts = [n for n,d in self.graph.nodes(data=True) if not d['switch']]
        tag = 1
        group = 1
        for src in hosts:
            for dst in hosts:
                if src == dst:
                    continue
                entry = next(iter(self.graph[src]))
                exit_switch = next(iter(self.graph[dst]))
                dp = self.datapaths[self.graph.nodes[entry]['dpid']]
                p, o = dp.ofproto_parser, dp.ofproto
                match = dict(in_port=self.graph[entry][src]['ports'][entry], eth_type=0x0800,
                             ipv4_dst=self.graph.nodes[dst]['ip'])
                if entry == exit_switch:
                    self.flow(dp, 2, 200, match, [self.output(dp, entry, dst)])
                    continue
                primary, secondary = model.disjoint_paths(self.switches, entry, exit_switch)
                buckets = []
                for path in (primary, secondary):
                    vlan = o.OFPVID_PRESENT | tag
                    outport = self.graph[path[0]][path[1]]['ports'][entry]
                    buckets.append(p.OFPBucket(watch_port=outport, watch_group=o.OFPG_ANY,
                        actions=[p.OFPActionPushVlan(),p.OFPActionSetField(vlan_vid=vlan),p.OFPActionOutput(outport)]))
                    for index in range(1, len(path)):
                        sw = path[index]
                        next_hop = dst if index == len(path)-1 else path[index+1]
                        hop = self.datapaths[self.graph.nodes[sw]['dpid']]
                        hp = hop.ofproto_parser
                        actions = ([hp.OFPActionPopVlan()] if index == len(path)-1 else []) + [self.output(hop,sw,next_hop)]
                        # If a downstream access link fails, locally detour via a
                        # distinct VLAN along a path avoiding that physical edge.
                        if index < len(path)-1 and next_hop.startswith('a'):
                            alt = self.switches.copy()
                            alt.remove_edge(sw,next_hop)
                            import networkx as nx
                            detour = nx.shortest_path(alt, sw, next_hop, weight='delay_ms')
                            repair_tag = o.OFPVID_PRESENT | (tag+1000)
                            repair_port = self.graph[sw][detour[1]]['ports'][sw]
                            gid = 10000 + tag
                            normal_port = self.graph[sw][next_hop]['ports'][sw]
                            hop.send_msg(hp.OFPGroupMod(hop, o.OFPGC_ADD,o.OFPGT_FF,gid,[
                                hp.OFPBucket(watch_port=normal_port,watch_group=o.OFPG_ANY,actions=actions),
                                hp.OFPBucket(watch_port=repair_port,watch_group=o.OFPG_ANY,
                                    actions=[hp.OFPActionSetField(vlan_vid=repair_tag),hp.OFPActionOutput(repair_port)])]))
                            for j in range(1,len(detour)):
                                ds = detour[j]
                                dd = self.datapaths[self.graph.nodes[ds]['dpid']]
                                pp = dd.ofproto_parser
                                da = ([pp.OFPActionPopVlan(), self.output(dd,ds,dst)] if j==len(detour)-1
                                      else [self.output(dd,ds,detour[j+1])])
                                self.flow(dd,2,400,dict(vlan_vid=repair_tag,eth_type=0x0800,ipv4_dst=self.graph.nodes[dst]['ip']),da)
                            actions = [hp.OFPActionGroup(gid)]
                        self.flow(hop,2,300,dict(vlan_vid=vlan,eth_type=0x0800,ipv4_dst=self.graph.nodes[dst]['ip']),actions)
                    tag += 1
                dp.send_msg(p.OFPGroupMod(dp,o.OFPGC_ADD,o.OFPGT_FF,group,buckets))
                self.flow(dp,2,200,match,[p.OFPActionGroup(group)])
                group += 1
        for dp in self.datapaths.values():
            msg = dp.ofproto_parser.OFPBarrierRequest(dp)
            dp.set_xid(msg)
            self.pending[(dp.id,msg.xid)] = 'initial'
            dp.send_msg(msg)

    @set_ev_cls(ofp_event.EventOFPBarrierReply, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def barrier(self, ev):
        key = (ev.msg.datapath.id,ev.msg.xid)
        kind = self.pending.pop(key, None)
        if kind == 'initial':
            self.ready.add(ev.msg.datapath.id)
            if len(self.ready)==7:
                self.event('ready')
                (self.directory/'controller_ready').write_text('ready\n')

    @set_ev_cls(ofp_event.EventOFPPortStatus, MAIN_DISPATCHER)
    def port(self, ev):
        self.event('port_status',dpid=ev.msg.datapath.id, port=ev.msg.desc.port_no,
                   state=ev.msg.desc.state, reason=ev.msg.reason)
        # Fast failover is proactive: no reactive FlowMod is sent or invented.

    @set_ev_cls(ofp_event.EventOFPErrorMsg, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def error(self, ev):
        self.event('openflow_error',type=ev.msg.type,code=ev.msg.code)
        (self.directory/'controller_error').write_text(repr(ev.msg))
