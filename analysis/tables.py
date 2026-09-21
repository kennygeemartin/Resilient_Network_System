"""No manually transcribed quantitative tables."""
import pandas as pd
from scripts.common import ROOT,digest,dump

if __name__=='__main__':
    manifest={}
    for name in ('descriptive','paired','omnibus','security_overhead'):
        source=ROOT/f'results/statistics/{name}.csv'
        frame=pd.read_csv(source)
        frame.to_csv(ROOT/f'tables/{name}.csv',index=False)
        # tabular text avoids an optional templating dependency.
        def escape(value):
            return str(value).replace('_',r'\_').replace('%',r'\%')
        lines=[r'\begin{tabular}{'+'l'*len(frame.columns)+'}', ' & '.join(map(escape,frame.columns))+r' \\ \hline']
        for row in frame.itertuples(index=False,name=None):
            lines.append(' & '.join('NA' if pd.isna(x) else escape(f'{x:.6g}' if isinstance(x,float) else x) for x in row)+r' \\')
        lines.append(r'\end{tabular}')
        (ROOT/f'tables/{name}.tex').write_text('\n'.join(lines)+'\n')
        manifest[name]=digest(source)
    dump(ROOT/'tables/provenance.json',manifest)
