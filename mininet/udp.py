"""Monotonic-clock UDP traffic. Packet size includes this header, excludes UDP/IP."""
import argparse
import csv
import heapq
import json
import socket
import struct
import time
from pathlib import Path

HEADER = struct.Struct('!4sIQBQQI')
MAGIC = b'CMN1'
PACKET_FIELDS = ['run_id','architecture','scenario','seed','flow_id','class','sequence',
                 'scheduled_ns','send_ns','receive_ns','latency_ns','deadline_ns',
                 'deadline_missed','packet_bytes']
SENT_FIELDS = ['flow_id','class','sequence','scheduled_ns','send_ns','packet_bytes','status']

def packet(flow, sequence, cls, scheduled, sent, deadline, size):
    header = HEADER.pack(MAGIC,flow,sequence,cls,scheduled,sent,deadline)
    if size < len(header):
        raise ValueError('Packet size below header size')
    return header + bytes(size-len(header))

def decode(data):
    fields = HEADER.unpack_from(data)
    if fields[0] != MAGIC:
        raise ValueError('Unknown protocol')
    return fields[1:]

def send(spec, output):
    sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,4*1024*1024)
    queue = []
    for flow in spec['flows']:
        for seq,offset in enumerate(flow['offsets_ns']):
            heapq.heappush(queue,(spec['start_ns']+offset,flow['id'],seq))
    flows = {f['id']:f for f in spec['flows']}
    with open(output,'x',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=SENT_FIELDS)
        writer.writeheader()
        while queue:
            scheduled,fid,sequence = heapq.heappop(queue)
            flow = flows[fid]
            delay = (scheduled-time.monotonic_ns())/1e9
            if delay > 0:
                time.sleep(delay)
            now = time.monotonic_ns()
            status = 'sent'
            if now-scheduled > flow['deadline_ns']:
                status = 'scheduler_miss'
            else:
                sock.setsockopt(socket.IPPROTO_IP,socket.IP_TOS,flow['dscp']<<2)
                data = packet(fid,sequence,flow['class'],scheduled,now,flow['deadline_ns'],flow['bytes'])
                try:
                    sock.sendto(data,(spec['destination'],spec['port']))
                except OSError:
                    status = 'send_error'
            writer.writerow(dict(flow_id=fid,**{'class':f'C{flow["class"]}'},sequence=sequence,
                scheduled_ns=scheduled,send_ns=now if status=='sent' else '',
                packet_bytes=flow['bytes'],status=status))
    sock.close()

def receive(spec, output, relay=False):
    sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,8*1024*1024)
    sock.bind(('0.0.0.0',spec['port']))
    sock.settimeout(0.2)
    relay_socket = socket.socket(socket.AF_INET,socket.SOCK_DGRAM) if relay else None
    with open(output,'x',newline='') as f:
        writer = csv.DictWriter(f,fieldnames=PACKET_FIELDS)
        writer.writeheader()
        Path(str(output)+'.ready').write_text('ready\n')
        while time.monotonic_ns() < spec['end_ns']:
            try:
                data,_ = sock.recvfrom(65535)
                now = time.monotonic_ns()
            except socket.timeout:
                continue
            try:
                flow,sequence,cls,scheduled,sent,deadline = decode(data)
            except (ValueError,struct.error):
                continue
            writer.writerow(dict(run_id=spec['run_id'],architecture=spec['architecture'],
                scenario=spec['scenario'],seed=spec['seed'],flow_id=flow,**{'class':f'C{cls}'},
                sequence=sequence,scheduled_ns=scheduled,send_ns=sent,receive_ns=now,
                latency_ns=now-sent,deadline_ns=deadline,deadline_missed=int(now-scheduled>deadline),packet_bytes=len(data)))
            if relay:
                cell = flow//100
                relay_socket.setsockopt(socket.IPPROTO_IP,socket.IP_TOS,spec['dscp'][str(cls)]<<2)
                relay_socket.sendto(data,(spec['actuators'][str(cell)],spec['actuator_port']))
    sock.close()

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode',choices=['send','receive','relay'])
    p.add_argument('spec')
    p.add_argument('output')
    args = p.parse_args()
    spec = json.loads(Path(args.spec).read_text())
    if args.mode == 'send':
        send(spec,args.output)
    else:
        receive(spec,args.output,args.mode=='relay')
