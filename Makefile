.PHONY: lint lint-py lint-kt lint-workflows typecheck test fmt fmt-py fmt-kt precommit codegen codegen-check

lint: lint-py lint-kt lint-workflows

lint-py:
	ruff check .
	mypy pycompose
	bandit -ll -q -r pycompose
	pydoclint pycompose
	lint-imports --config pyproject.toml
	python tools/limits.py
	@if [ -d examples/notes/app ]; then (cd examples/notes/app && lint-imports --config importlinter.toml); fi

lint-kt:
	@if [ -d android ]; then cd android && ./gradlew spotlessCheck detekt lintDebug; fi

lint-workflows:
	actionlint .github/workflows/*.yml

typecheck:
	mypy pycompose

codegen:
	python tools/schema/gen.py

codegen-check:
	python tools/schema/gen.py --check
	cd android && ./gradlew dumpComposeDefaults
	python tools/schema/check_upstream.py

test:
	pytest -q
	@if [ -d android ]; then cd android && ./gradlew testDebugUnitTest; fi

fmt:
	ruff format .
	ruff check --fix .
	@if [ -d android ]; then cd android && ./gradlew spotlessApply; fi

fmt-py:
	ruff format .
	ruff check --fix .

fmt-kt:
	@if [ -d android ]; then cd android && ./gradlew spotlessApply; fi

precommit:
	pre-commit run --all-files
