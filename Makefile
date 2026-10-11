.PHONY: lint lint-py lint-kt typecheck test fmt fmt-py fmt-kt precommit codegen codegen-check

lint: lint-py lint-kt

lint-py:
	ruff check .
	mypy pycompose
	bandit -ll -q -r pycompose
	lint-imports --config pyproject.toml

lint-kt:
	@if [ -d android ]; then cd android && ./gradlew spotlessCheck detekt lintDebug; fi

typecheck:
	mypy pycompose

codegen:
	python tools/schema/gen.py

codegen-check:
	python tools/schema/gen.py --check

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
