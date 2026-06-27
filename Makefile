.PHONY: dev install test eval inspect-data lint check-versions import-lint

dev:
	docker compose up -d redis postgres minio

install:
	python3 -m pip install -r requirements.txt

test:
	python3 -m unittest discover -s tests -p 'test_*.py'

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
