.PHONY: test measure image clean

test:
	uv run --extra dev pytest -q

image:
	uv run python -c "from speedproof.verifyperf.callgrind import ensure_image; ensure_image(); print('image ready')"

measure:
	uv run python -m speedproof.verifyperf.cli

clean:
	rm -rf .pytest_cache **/__pycache__
