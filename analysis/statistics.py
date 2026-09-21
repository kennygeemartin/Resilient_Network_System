"""Seed-level uncertainty, assumption checks, paired effects and Holm adjustment."""
import itertools
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.anova import AnovaRM
from statsmodels.stats.multitest import multipletests

def describe(values):
    v=np.asarray(values,dtype=float)
    v=v[np.isfinite(v)]
    n=len(v)
    if not n:
        return dict(n=0,mean=None,sd=None,se=None,ci_low=None,ci_high=None,median=None,iqr=None)
    mean=float(v.mean())
    sd=float(v.std(ddof=1)) if n>1 else None
    se=sd/np.sqrt(n) if sd is not None else None
    margin=float(stats.t.ppf(.975,n-1)*se) if n>1 else None
    return dict(n=n,mean=mean,sd=sd,se=se,ci_low=mean-margin if margin is not None else None,
                ci_high=mean+margin if margin is not None else None,median=float(np.median(v)),
                iqr=float(np.quantile(v,.75)-np.quantile(v,.25)))

def normal(values,alpha=.05):
    values=np.asarray(values)
    if len(values)<3:
        return False,None
    if np.ptp(values)<1e-12:
        return True,1.0
    p=float(stats.shapiro(values).pvalue)
    return p>alpha,p

def paired(a,b):
    delta=np.asarray(b)-np.asarray(a)
    ok,normal_p=normal(delta)
    if np.allclose(delta,0,rtol=0,atol=1e-12):
        test,stat,p='identical_pairs',0.0,1.0
    elif ok and np.std(delta,ddof=1)>1e-12:
        test='paired_t'
        stat,p=stats.ttest_rel(b,a)
    else:
        test='wilcoxon'
        stat,p=stats.wilcoxon(delta,zero_method='wilcox',alternative='two-sided',method='auto')
    sd=np.std(delta,ddof=1)
    nonzero=delta[np.abs(delta)>1e-12]
    ranks=stats.rankdata(np.abs(nonzero))
    rbc=float(np.sum(ranks*np.sign(nonzero))/np.sum(ranks)) if len(nonzero) else 0.0
    return dict(n=len(delta),test=test,statistic=float(stat),p=float(p),difference_b_minus_a=float(delta.mean()),
                dz=float(delta.mean()/sd) if sd>1e-12 else None,
                dz_reason='' if sd>1e-12 else 'zero_difference_variance',rank_biserial=rbc,normality_p=normal_p,
                **{'difference_'+k:v for k,v in describe(delta).items() if k in ('ci_low','ci_high')})

def omnibus(pivot):
    data=pivot.to_numpy()
    n,k=data.shape
    # Orthonormal contrasts exclude the singular grand-mean direction.
    contrasts=np.linalg.qr(np.column_stack([np.eye(k)[:,i]-np.eye(k)[:,-1] for i in range(k-1)]))[0]
    cov=np.cov(data@contrasts,rowvar=False)
    eig=np.linalg.eigvalsh(cov)
    if np.all(np.ptp(data,axis=1)<1e-12):
        return dict(test='identical_architectures',statistic=0.,p=1.,effect_size=0.,effect_name='kendall_W',sphericity_p=1.,normality_p=1.)
    residual=data-data.mean(axis=1,keepdims=True)-data.mean(axis=0,keepdims=True)+data.mean()
    normals=[normal(residual[:,i])[1] for i in range(k)]
    normal_p=min(p for p in normals if p is not None)
    d=k-1
    if np.any(eig<=1e-12):
        sphere_p=0.
    else:
        w=np.prod(eig)/(eig.mean()**d)
        correction=1-(2*d*d+d+2)/(6*d*(n-1))
        chi=-(n-1)*correction*np.log(min(1.,w))
        sphere_p=float(stats.chi2.sf(chi,d*(d+1)/2-1))
    if normal_p>.05 and sphere_p>.05:
        long=pivot.rename_axis('seed').reset_index().melt('seed',var_name='architecture',value_name='value')
        table=AnovaRM(long,'value','seed',within=['architecture']).fit().anova_table.iloc[0]
        f=float(table['F Value']);df1=float(table['Num DF']);df2=float(table['Den DF'])
        return dict(test='repeated_measures_anova',statistic=f,p=float(table['Pr > F']),
                    effect_size=f*df1/(f*df1+df2),effect_name='partial_eta_squared',sphericity_p=sphere_p,normality_p=normal_p)
    result=stats.friedmanchisquare(*[data[:,i] for i in range(k)])
    return dict(test='friedman',statistic=float(result.statistic),p=float(result.pvalue),
                effect_size=float(result.statistic/(n*(k-1))),effect_name='kendall_W',sphericity_p=sphere_p,normality_p=normal_p)

def compare(long):
    pairs,groups=[],[]
    for (tool,scenario,metric),frame in long.groupby(['tool','scenario','metric']):
        pivot=frame.pivot(index='seed',columns='architecture',values='value').dropna()
        if len(pivot)<30:
            continue  # Censored/undefined values are described but never silently treated as full paired data.
        family=[]
        for a,b in itertools.combinations(pivot.columns,2):
            family.append(dict(tool=tool,scenario=scenario,metric=metric,a=a,b=b,**paired(pivot[a],pivot[b])))
        if family:
            adjusted=multipletests([r['p'] for r in family],method='holm')[1]
            for row,p in zip(family,adjusted):
                row['p_holm']=float(p)
            pairs.extend(family)
        if len(pivot.columns)==4:
            groups.append(dict(tool=tool,scenario=scenario,metric=metric,n=len(pivot),**omnibus(pivot)))
    return pd.DataFrame(pairs),pd.DataFrame(groups)
