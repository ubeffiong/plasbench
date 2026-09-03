#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for test in test_scoring.py test_make_truth.py test_bin_matching.py test_merge_bin_metrics.py test_amr_truth.py test_recommendation_validation.py test_gplas_classifier_validation.py test_mob_to_gplas_classifier.py test_cohort_validation.py test_aggregate.py test_report_composition.py test_recovery_vocabulary.py test_explorer_view.py test_visual_report.py test_structural_and_annotation.py test_protein_annotation.py test_depth_ladder.py test_container_hygiene.py test_selection.py test_visualization_data.py; do
    python3 "$HERE/$test"
done
bash "$HERE/test_gplas_adapter.sh"
echo "ALL PLASBENCH TESTS PASSED"
