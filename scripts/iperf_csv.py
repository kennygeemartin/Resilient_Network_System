"""Lossless interval export of observed iperf3 receiver JSON into raw CSV."""
import csv
import json

FIELDS=['stream','start_s','end_s','seconds','bytes','bits_per_second','omitted']

def export(directory):
    paths=sorted(directory.glob('iperf_server_*.json'))
    if len(paths)!=8:
        raise ValueError('Expected eight iperf receiver records')
    with (directory/'iperf_intervals.csv').open('x',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=FIELDS)
        writer.writeheader()
        for path in paths:
            data=json.loads(path.read_text())
            if 'error' in data or not data.get('intervals'):
                raise ValueError(f'Failed iperf observation: {path}')
            for interval in data['intervals']:
                value=interval['sum']
                writer.writerow(dict(stream=path.stem,start_s=value['start'],end_s=value['end'],
                    seconds=value['seconds'],bytes=value['bytes'],bits_per_second=value['bits_per_second'],omitted=value.get('omitted',False)))
