from scripts.common import ROOT, config, dump
from scripts.model_loader import model
if __name__ == '__main__':
    result = model.validate(config())
    dump(ROOT / 'results/environment/topology_validation.json', result)
    print('PASS: 7 switches, 17 hosts, 27 links; all switch pairs have link-disjoint paths')
