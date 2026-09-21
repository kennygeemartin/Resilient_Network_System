"""Summarize actual development evidence without producing publication metrics."""
import json
from scripts.common import ROOT,dump,verify_seal,source_digest,digest

def report():
    runs=[]
    for path in sorted((ROOT/'results/development/ifogsim').glob('*')):
        if not path.is_dir():
            continue
        verify_seal(path)
        meta=json.loads((path/'metadata.json').read_text())
        item=dict(path=path.relative_to(ROOT).as_posix(),status=meta['status'],seed=meta['seed'],
                  architecture=meta['architecture'],development_only=meta.get('development_only'),
                  environment_ready=meta['environment']['ready'],source_sha256=meta['provenance']['source_sha256'])
        if meta['status']=='complete':
            import pandas as pd
            data=pd.read_csv(path/'tuples.csv')
            item.update(observed_completed_tuples=len(data),observed_modules=int(data.module.nunique()))
            item.update(tuple_sha256=digest(path/'tuples.csv'),placement_sha256=digest(path/'placement.csv'))
            if data.module.nunique()!=20 or data.isna().any().any():
                raise ValueError('Incomplete Java development observations')
        runs.append(item)
    matched=[r for r in runs if r['status']=='complete' and r['source_sha256']==source_digest() and r['architecture'] in ('A1','A2','A3')]
    invariance=None
    if len({r['architecture'] for r in matched})==3:
        invariance=len({r['tuple_sha256'] for r in matched})==1 and len({r['placement_sha256'] for r in matched})==1
        if not invariance:raise ValueError('A1/A2/A3 compute-only arms unexpectedly differ')
    dump(ROOT/'results/environment/development_validation.json',dict(publication_results=False,compute_ablation_invariance=invariance,
         target_environment_smoke_passed=False,current_source_sha256=source_digest(),runs=runs))
    include=[]
    for folder in ('config','mininet','ifogsim','analysis','scripts','tests','docs'):
        include.extend(p.relative_to(ROOT).as_posix() for p in (ROOT/folder).rglob('*')
                       if p.is_file() and '__pycache__' not in p.parts)
    include.extend(p.name for p in ROOT.iterdir() if p.is_file())
    include.extend(['third_party/ifogsim/ [pinned gitlink]','third_party/mininet/ [pinned gitlink]',
                    'results/raw/ [no publication data]','results/processed/','results/statistics/',
                    'results/environment/','figures/','tables/'])
    (ROOT/'results/environment/repository_tree.txt').write_text('\n'.join(sorted(include))+'\n')
    print(json.dumps(dict(development_runs=len(runs),complete=sum(r['status']=='complete' for r in runs),
                         publication_campaign_started=False),indent=2))

if __name__=='__main__':report()
