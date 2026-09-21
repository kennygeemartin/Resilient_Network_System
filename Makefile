SHELL := /bin/bash
PYTHON ?= .venv/bin/python
JAVA_HOME ?= /usr/lib/jvm/java-11-openjdk-amd64
export JAVA_HOME
export PATH := $(JAVA_HOME)/bin:$(PATH)

.PHONY: setup capture-env topology test audit smoke preflight ifogsim mininet security analyze figures tables verify reproduce analysis-only matrix
setup:
	bash scripts/setup.sh
capture-env:
	PYTHON=$(PYTHON) bash scripts/capture_environment.sh
topology:
	$(PYTHON) -m scripts.validate_topology
test:
	$(PYTHON) -m scripts.run_tests
audit:
	$(PYTHON) -m scripts.audit_constants
matrix:
	$(PYTHON) -m scripts.matrix
smoke: capture-env topology test audit
	sudo env PATH="$(PATH)" $(PYTHON) -m scripts.run_mininet --smoke
	$(PYTHON) -m scripts.run_ifogsim --smoke
preflight:
	$(PYTHON) -m scripts.preflight --gate
ifogsim:
	$(PYTHON) -m scripts.run_ifogsim
mininet:
	sudo env PATH="$(PATH)" $(PYTHON) -m scripts.run_mininet
security:
	sudo env PATH="$(PATH)" $(PYTHON) -m scripts.run_mininet --security
analyze:
	$(PYTHON) -m analysis.process
figures:
	$(PYTHON) -m analysis.figures
tables:
	$(PYTHON) -m analysis.tables
verify:
	$(PYTHON) -m scripts.verify_results
# Recursive invocations enforce order, even when the caller uses make -j.
reproduce:
	$(MAKE) capture-env
	$(MAKE) smoke
	$(MAKE) preflight
	$(MAKE) ifogsim
	$(MAKE) mininet
	$(MAKE) security
	$(MAKE) analyze
	$(MAKE) figures
	$(MAKE) tables
	$(MAKE) verify
analysis-only:
	$(MAKE) analyze
	$(MAKE) figures
	$(MAKE) tables
	$(MAKE) verify
