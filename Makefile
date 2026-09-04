# Convenience wrapper. `make help` to list targets.
.PHONY: help demo test setup db check run download truth assemble tools score aggregate clean

help:
	@echo "Targets:"
	@echo "  make demo       - offline synthetic end-to-end (no tools needed)"
	@echo "  make test       - unit-test the scoring math"
	@echo "  make setup      - create the conda env"
	@echo "  make db         - download the Platon database"
	@echo "  make check      - verify installed dependencies (stage 0)"
	@echo "  make run        - full pipeline, stages 0-6"
	@echo "  make download / truth / assemble / tools / score / aggregate - single stages"
	@echo "  make clean      - remove demo/tmp/pycache (keeps data & results)"

demo:      ; bash test/run_demo.sh
test:      ; bash test/run_tests.sh
setup:     ; bash env/setup_conda.sh
db:        ; bash env/download_platon_db.sh
check:     ; bash scripts/run_all.sh 0
run:       ; bash scripts/run_all.sh
download:  ; bash scripts/run_all.sh 1
truth:     ; bash scripts/run_all.sh 2
assemble:  ; bash scripts/run_all.sh 3
tools:     ; bash scripts/run_all.sh 4
score:     ; bash scripts/run_all.sh 5
aggregate: ; bash scripts/run_all.sh 6

clean:
	rm -rf results_demo tmp
	find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true
