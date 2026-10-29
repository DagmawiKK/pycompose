.PHONY: lint lint-py lint-kt lint-workflows typecheck test fmt fmt-py fmt-kt precommit codegen codegen-check spec

lint: lint-py lint-kt lint-workflows

lint-py:
	ruff check .
	mypy packages/pycompose/src/pycompose
	bandit -ll -q -r packages/pycompose/src/pycompose
	pydoclint packages/pycompose/src/pycompose
	lint-imports --config pyproject.toml
	python tools/limits.py
	@if [ -d examples/notes/app ]; then (cd examples/notes/app && lint-imports --config importlinter.toml); fi

lint-kt:
	@if [ -d android ]; then cd android && ./gradlew spotlessCheck detekt lintDebug; fi

lint-workflows:
	actionlint .github/workflows/*.yml

typecheck:
	mypy packages/pycompose/src/pycompose

codegen:
	python tools/schema/gen.py

spec:
	python tools/spec/check.py

codegen-check:
	python tools/schema/gen.py --check
	cd android && ./gradlew dumpComposeApi dumpComposeDefaults
	PYCOMPOSE_NATIVE_API_TESTS=1 pytest -q tests/test_classpath_dump.py tests/test_component_proposals.py tests/test_composegen.py
	python -m pycompose.compiler generate --check

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
