"""Avoid shadowing the upstream mininet Python package with this source directory."""
import importlib.util
from scripts.common import ROOT
spec = importlib.util.spec_from_file_location('experiment_model', ROOT / 'mininet/model.py')
model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(model)
