"""OS-Ken 4.2.2 library entry point (the wheel has no osken-manager CLI)."""
import logging
import argparse
from scripts.common import ROOT,config

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--listen-port',type=int,default=config()['controller']['port'])
    args=parser.parse_args()
    from os_ken import cfg
    from os_ken.base.app_manager import AppManager
    # Import registers the OF transport options before parsing configuration.
    from os_ken.controller import controller as transport
    logging.basicConfig(level=logging.INFO)
    cfg.CONF(args=['--ofp-listen-host',config()['controller']['listen_host'],'--ofp-tcp-listen-port',str(args.listen_port)])
    AppManager.run_apps([str(ROOT/'mininet/controller/resilient.py'),'os_ken.controller.ofp_handler'])

if __name__=='__main__':
    main()
