"""Conservative plotting audit; cannot infer the provenance of every scalar.

No previous manuscript was used as input. Configuration constants and synthetic
unit-test fixtures are allowed; numeric result arrays in plotting code are not.
"""
import ast
from scripts.common import ROOT, dump

def audit_file(path):
    tree=ast.parse(path.read_text())
    errors=[]
    for node in ast.walk(tree):
        if isinstance(node,(ast.List,ast.Tuple,ast.Set)) and node.elts and all(
            isinstance(x,ast.Constant) and isinstance(x.value,(float,int)) for x in node.elts):
            # A single figsize tuple is presentation geometry, not a result array.
            geometry=any(isinstance(p,ast.keyword) and p.arg=='figsize' and p.value is node for p in ast.walk(tree))
            if not geometry:
                errors.append(f'{path}:{node.lineno}: literal numeric array in plotting code')
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in ('full','zeros','ones','linspace'):
            errors.append(f'{path}:{node.lineno}: generated constant result vector requires review')
    return errors

def audit():
    errors=audit_file(ROOT/'analysis/figures.py')
    report=dict(passed=not errors,errors=errors,
        scope='AST scan of plotting code for literal or generated constant result arrays',
        provenance_statement='No prior manuscript numerical results were supplied to the implementation or used as expected outputs.',
        limitation='This audit cannot prove provenance of arbitrary scalars. Review config assumptions and source changes.')
    dump(ROOT/'results/environment/constant_audit.json',report)
    if errors:
        raise ValueError('\n'.join(errors))
    print('PASS: no hard-coded result arrays in plotting code; figures read data-derived CSVs')
    return report

if __name__=='__main__':
    audit()
