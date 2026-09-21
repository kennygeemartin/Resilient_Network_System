"""Pure topology and path model, importable without the Mininet runtime."""
import networkx as nx

def topology(c):
    graph = nx.Graph()
    ports = {}
    def node(name, **attrs):
        graph.add_node(name, **attrs)
        ports[name] = 0
    def link(a, b, kind):
        ports[a] += 1
        ports[b] += 1
        graph.add_edge(a, b, kind=kind, ports={a: ports[a], b: ports[b]}, **c['topology']['links'][kind])
    for i in range(1, 5):
        node(f'a{i}', switch=True, dpid=i)
    for i in range(1, 3):
        node(f'g{i}', switch=True, dpid=4+i)
    node('core', switch=True, dpid=7)
    ident = 1
    for cell in range(1, 5):
        for role in ('s1', 's2', 'act', 'fog'):
            name = f'c{cell}{role}'
            node(name, switch=False, cell=cell, role=role,
                 ip=f'10.0.0.{ident}', mac=f'02:00:00:00:00:{ident:02x}')
            link(name, f'a{cell}', 'fog_access' if role == 'fog' else 'edge_access')
            ident += 1
        for agg in ('g1', 'g2'):
            link(f'a{cell}', agg, 'access_aggregation')
    node('cloud', switch=False, cell=0, role='cloud', ip=f'10.0.0.{ident}', mac=f'02:00:00:00:00:{ident:02x}')
    for agg in ('g1', 'g2'):
        link(agg, 'core', 'aggregation_core')
    link('core', 'cloud', 'core_cloud')
    return graph

def switch_graph(graph):
    return graph.subgraph([n for n,d in graph.nodes(data=True) if d['switch']]).copy()

def disjoint_paths(graph, source, destination):
    """Minimum-delay primary; shortest backup after removing its undirected edges.

    Access-host and cloud-host links are single-homed and excluded from protection.
    This is a graph algorithm, not an online ILP.
    """
    if source == destination:
        return [source], [source]
    first = nx.shortest_path(graph, source, destination, weight='delay_ms')
    remaining = graph.copy()
    remaining.remove_edges_from(zip(first, first[1:]))
    second = nx.shortest_path(remaining, source, destination, weight='delay_ms')
    return first, second

def rules(c, architecture):
    g = topology(c)
    entries = []
    service = c['traffic']['service_port']
    actuator = c['traffic']['actuator_port']
    security = c['traffic']['security_port']
    background = c['traffic']['C3']['port']
    for cell in range(1, 5):
        fog = 'cloud' if architecture == 'A0' else f'c{cell}fog'
        for sensor in (f'c{cell}s1', f'c{cell}s2'):
            entries.append(dict(src=sensor, dst=fog, protocol=17, port=service))
            entries.append(dict(src=sensor, dst='cloud', protocol=6, port=background+cell*2+(sensor.endswith('2'))))
            entries.append(dict(src='cloud', dst=sensor, protocol=6, source_port=background+cell*2+(sensor.endswith('2'))))
            entries.append(dict(src=sensor, dst=f'c{cell}act', protocol=17, port=security))
        entries.append(dict(src=fog, dst=f'c{cell}act', protocol=17, port=actuator))
    return entries

def authorized(c, architecture, source, destination, protocol, port, ingress_ok=True):
    if architecture != 'A3':
        return True
    return ingress_ok and any(r['src']==source and r['dst']==destination and
        r['protocol']==protocol and r.get('port')==port for r in rules(c, architecture))

def validate(c):
    assert c['topology']['cells'] == 4 and c['topology']['sensors_per_cell'] == 2
    g = topology(c)
    s = switch_graph(g)
    assert len(s)==7 and len(g)==24 and g.number_of_edges()==27
    checks = []
    for a in s:
        for b in s:
            p, q = disjoint_paths(s, a, b)
            pe = {frozenset(e) for e in zip(p,p[1:])}
            qe = {frozenset(e) for e in zip(q,q[1:])}
            assert not pe & qe
            checks.append({'source':a,'destination':b,'primary':p,'secondary':q})
    return {'passed':True, 'switches':7, 'hosts':17, 'links':27, 'paths':checks,
            'unprotected':'All host attachments are single-homed; no compute failover is assumed.'}
