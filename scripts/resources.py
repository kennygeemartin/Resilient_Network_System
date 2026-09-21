"""Host and process-tree resource observations; never counted as network metrics."""
import argparse
import csv
import time
from pathlib import Path
import psutil

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('output')
    p.add_argument('parent',type=int)
    p.add_argument('end_ns',type=int)
    p.add_argument('--stop-file')
    args = p.parse_args()
    parent = psutil.Process(args.parent)
    with open(args.output,'x',newline='') as f:
        w = csv.writer(f)
        w.writerow(['monotonic_ns','host_cpu_percent','host_memory_used_bytes','tree_rss_bytes','tree_processes'])
        f.flush()
        Path(args.output+'.ready').write_text('ready\n')
        psutil.cpu_percent()
        while time.monotonic_ns() < args.end_ns:
            if args.stop_file and Path(args.stop_file).exists():
                break
            children = parent.children(recursive=True)+[parent]
            rss = 0
            for child in children:
                try:
                    rss += child.memory_info().rss
                except psutil.NoSuchProcess:
                    pass
            w.writerow([time.monotonic_ns(),psutil.cpu_percent(),psutil.virtual_memory().used,rss,len(children)])
            f.flush()
            time.sleep(1)
