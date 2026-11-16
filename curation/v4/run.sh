set -e
cd f:/tmp/pb
SP='--species Escherichia\ coli'
common=(--species "Escherichia coli" --species "Klebsiella pneumoniae" --species "Salmonella enterica" --species "Staphylococcus aureus" --species "Enterobacter hormaechei" --date-basis earliest_public)
python3 python/import_contributed_cohort.py --arm recent --released-after 2025-01-01 --max-clusters-per-species 40 "${common[@]}" --out-dir curation/v4/recent
python3 python/import_contributed_cohort.py --arm older --released-before 2024-12-31 --max-clusters-per-species 80 "${common[@]}" --out-dir curation/v4/older
python3 python/resolve_contributed_cohort.py --candidates curation/v4/recent/candidates.tsv --candidates curation/v4/older/candidates.tsv --out-dir curation/v4/resolved --cache curation/v4/resolve_cache.json --target-per-species 20 --min-recent 10
for try in 1 2 3; do
  if python3 python/validate_cohort.py --samples curation/v4/resolved/resolved.tsv --online --ledger cohorts/accepted_accessions.tsv --write-lock curation/v4/resolved/resolved.lock.json; then echo VALIDATED; break; fi
  echo "validation attempt $try failed; retrying"; sleep 20
done
