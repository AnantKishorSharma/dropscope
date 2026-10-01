.PHONY: help venv install test demo run clean

PY ?= python3
VENV := .venv
BIN := $(VENV)/bin

help:
	@echo "make install   - create venv and install (editable) with test deps"
	@echo "make test      - run the pytest suite"
	@echo "make demo      - run the live drop-attribution demo (http://127.0.0.1:8000)"
	@echo "make clean     - remove venv and caches"

$(VENV):
	$(PY) -m venv $(VENV)

install: $(VENV)
	$(BIN)/python -m pip install --upgrade pip
	$(BIN)/python -m pip install -e ".[test]"

test:
	$(BIN)/python -m pytest

demo:
	$(BIN)/python -m dropscope.demo

run: demo

clean:
	rm -rf $(VENV) .pytest_cache **/__pycache__ src/*.egg-info
