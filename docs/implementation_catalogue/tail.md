
## 10. Tests and how to run them

The suite lives in `test/` (script-style Python tests, shell stage tests with stand-in tools, and real-binary checks). Run all of it with `python -m plasbench test` or
`bash test/run_tests.sh`; run one with `python test/test_<name>.py`. It runs on every pull request in CI (the `test` job and a container build). Shell stage tests need
Linux (WSL on Windows) and minimap2.

| Kind | What it proves | Examples |
|---|---|---|
| Unit and adversarial scoring | Each metric against hand-computed values and degenerate predictions | `test_scoring.py`, `test_scoring_adversarial.py` |
| Stage tests | A stage produces the right tables from stand-in tools | `test_stage_dimensions.sh`, `test_short_read_qc_stage.sh`, `test_assembly_selection_stage.sh` |
| Cross-checks | Agreement with an independent implementation | `test_plaseval_crosscheck.py`, `test_plaseval_gate.py`, `test_plaseval_cohort.py`, `test_scoring_real_minimap2.py` |
| Wiring and drift | Every script, tool and output is connected; nothing is declared but not installed | `test_script_wiring.py`, `test_install_wiring.py`, `test_report_surfaces.py` |
| Documentation | Documents agree with the code and each other | `test_guide_docs.py`, `test_independent_review_ledger.py`, `test_external_review_log.py`, `test_reviewer_matrix.py`, `test_implementation_catalogue.py` |

A passing test is not scientific validation (section 1). The independent evidence is listed in [`EXTERNAL_REVIEW_LOG.md`](EXTERNAL_REVIEW_LOG.md).

## 11. What is not implemented

Stated plainly so no one has to find it by looking. Full detail and a status for every reviewer question: [`REVIEWER_ASSESSMENT_MATRIX.md`](REVIEWER_ASSESSMENT_MATRIX.md).

- **A real-data run of the whole tool set.** Nothing about ranking or generalisation is demonstrated on real data until one exists. This is the largest open item.
- **Independent third-party re-run** and an **external validation cohort**.
- **Frozen, platform-specific thresholds** for QC, assembly eligibility, candidate relationships and the CPRR limits, set from pilot data.
- **Evidence beyond NCBI metadata** for most references, and plasmid-free, hard-structure and taxonomically broader isolates in the released cohorts.
- **Telling a novel plasmid from an incorrect reconstruction** (the one major gap in the 215-question assessment).
- **A seven-step tool validation ladder.** The registry has four states; output-validated, benchmark-validated and real-data-validated tools are not claimed.
- **A real multi-assembler comparison and a real-cohort ranking-stability result**; the modules exist and are tested on constructed cohorts.
- **A measured resource pilot** on the target hardware; the resource figures in the README are estimates.
- **A comparison with the figures printed in the PlasEval paper**, and the one isolate-tool pair the original program could not finish.
- **Out of scope by design:** plasmid clustering, communities, database search, relatedness, backbone/accessory analysis, phylogeny, and any diagnostic or epidemiological inference.

## 12. Keeping this document true

Sections 5 to 9 are generated from the repository and checked by `test/test_implementation_catalogue.py`: adding a module, a registered tool or an output without listing it here
fails the test. Sections 3 and 4 are written by hand; the test also checks that every `python/`, `test/`, `config/`, `docs/`, `scripts/` and `cohorts/` path they name exists. When you
add a capability: write its section in 3, regenerate the indexes with `python python/build_implementation_catalogue.py`, and add the change to the changelog.
