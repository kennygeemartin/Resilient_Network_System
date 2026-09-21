"""Actual UDP probes; spoof tests send Ethernet frames on the attacker's port."""
import argparse
import csv
import json
import socket
import time
from pathlib import Path

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('mode',choices=['send','receive'])
    p.add_argument('spec')
    p.add_argument('output')
    args = p.parse_args()
    s = json.loads(Path(args.spec).read_text())
    with open(args.output,'x',newline='') as f:
        w = csv.writer(f)
        w.writerow(['probe_id','kind','monotonic_ns'])
        sock = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        if args.mode == 'receive':
            sock.bind(('0.0.0.0',s['port']))
            sock.settimeout(0.2)
            Path(args.output+'.ready').write_text('ready\n')
            while time.monotonic_ns() < s['end_ns']:
                try:
                    data,_ = sock.recvfrom(4096)
                    probe,kind = data.decode().split(':')
                    w.writerow([int(probe),kind,time.monotonic_ns()])
                except socket.timeout:
                    pass
        else:
            if s.get('spoof'):
                from scapy.all import Ether, IP, UDP, Raw, sendp
            for i in range(s['count']):
                payload = f'{i}:{s["kind"]}'.encode()
                if s.get('spoof'):
                    frame = Ether(src=s['spoof_mac'],dst=s['dst_mac'])/IP(src=s['spoof_ip'],dst=s['destination'])/UDP(dport=s['port'])/Raw(payload)
                    sendp(frame,iface=s['interface'],verbose=False)
                else:
                    sock.sendto(payload,(s['destination'],s['port']))
                w.writerow([i,s['kind'],time.monotonic_ns()])
                time.sleep(s['interval_ms']/1000)
