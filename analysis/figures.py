"""All ordinate values and uncertainty come from data-derived statistics CSVs."""
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scripts.common import ROOT, digest, dump, config

def panel(frame,title,ylabel,filename,xcolumn='scenario'):
    fig,ax=plt.subplots(figsize=(8,4.8),layout='constrained')
    categories=sorted(frame[xcolumn].unique())
    if categories and all(str(x).startswith('load_') for x in categories):
        categories.sort(key=lambda x:config()['loads'][x.removeprefix('load_')])
    architectures=sorted(frame.architecture.unique())
    missing=[]
    for index,architecture in enumerate(architectures):
        part=frame[frame.architecture==architecture].set_index(xcolumn).reindex(categories)
        x=np.arange(len(categories))+(index-(len(architectures)-1)/2)*.12
        estimable=part.n.ge(2)&part['mean'].notna()
        ax.errorbar(x[estimable],part.loc[estimable,'mean'],yerr=np.vstack((part.loc[estimable,'mean']-part.loc[estimable,'ci_low'],part.loc[estimable,'ci_high']-part.loc[estimable,'mean'])),
                    fmt='o-',capsize=3,label=architecture)
        for category,row in part.iterrows():
            if row.n<2 or ('n_missing' in row and row.n_missing>0):
                missing.append(f'{architecture}/{category}: n={int(row.n)}, missing={int(row.get("n_missing",0))}')
    ax.set_xticks(np.arange(len(categories)),categories,rotation=15,ha='right')
    ax.set(title=title,ylabel=ylabel)
    ax.legend();ax.grid(axis='y',alpha=.25)
    if missing:
        fig.text(.01,.01,'; '.join(missing),fontsize=6,wrap=True)
        fig.set_size_inches(10,6)
    fig.savefig(ROOT/'figures'/filename,dpi=200)
    plt.close(fig)

def main():
    statistics=ROOT/'results/statistics/descriptive.csv'
    df=pd.read_csv(statistics)
    network=df[df.tool=='mininet']
    specs=[('latency_ms','load_','Critical packet latency (95% t CI)','Observed latency (ms)','latency.pdf'),
           ('tcp_throughput_mbps','load_','TCP receiver throughput (95% t CI)','Throughput (Mbps)','throughput_load.pdf'),
           ('availability','load_','Service availability (95% t CI)','Successful / scheduled cycles','availability.pdf'),
           ('rto_ms',None,'Recovery time (95% t CI; recovered runs only)','RTO (ms)','rto_failures.pdf')]
    for metric,prefix,title,label,name in specs:
        part=network[network.metric==metric]
        part=part[part.scenario.str.startswith(prefix)] if prefix else part[part.scenario.isin(['link_fail_stop','fog_node_fail_stop','combined_failure'])]
        if part.empty:
            raise ValueError(f'Missing data for {name}')
        panel(part,title,label,name)
    for metric in ('attack_block_rate','authorized_allow_rate','false_block_rate'):
        panel(network[network.metric==metric],metric.replace('_',' ')+' (95% t CI)','Fraction',metric+'.pdf')
    overhead=pd.read_csv(ROOT/'results/statistics/security_overhead.csv')
    part=overhead[overhead.metric=='latency_ms'].copy()
    part['architecture']='A3 minus A2 (paired)'
    panel(part,'Security overhead (paired 95% t CI)','Latency difference (ms)','security_overhead.pdf')
    dump(ROOT/'figures/provenance.json',{'descriptive_sha256':digest(statistics),
         'overhead_sha256':digest(ROOT/'results/statistics/security_overhead.csv'),
         'raw_manifest_sha256':digest(ROOT/'results/processed/provenance.json')})

if __name__=='__main__':
    main()
