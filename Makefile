.PHONY: dev install install-dev install-deep test test-studio eval eval-studio inspect-data lint check-versions import-lint studio build-macos smoke-macos

dev:
	docker compose up -d redis postgres minio

install:
	python3 -m pip install -r requirements.txt

install-dev:
	python3 -m pip install -r requirements-dev.txt

install-deep:
	python3 -m pip install -r requirements-deep-learning.txt

test:
	python3 -m unittest discover -s tests -p 'test_*.py'

test-studio:
	python3 -m unittest discover -s tests -p 'test_studio_app.py' -v

studio:
	python3 -m spatialmind.app --data-root data

build-macos:
	python3 scripts/build_macos_app.py --clean --dmg

smoke-macos:
	python3 scripts/smoke_test_macos_app.py

eval-studio:
	python3 scripts/evaluate_studio_workflow.py --out outputs/studio_evaluation

eval:
	python3 -m eval.runner --cases eval/test_cases --data data/demo_manifest.json --out outputs/eval_report.json

inspect-data:
	python3 -m spatialmind.cli --inspect-data --data data --inspect-out outputs/dataset_report.json

lint:
	PYTHONPYCACHEPREFIX=.pycache python3 -m compileall spatialmind eval tests

check-versions:
	python3 -m spatialmind.versioning

import-lint:
	lint-imports
