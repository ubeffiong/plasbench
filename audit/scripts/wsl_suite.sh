#!/usr/bin/env bash
set -u
SRC="${1:?usage: wsl_suite.sh <path to the exported main tree, as seen from WSL>}"
rm -rf ~/pb_main && mkdir -p ~/pb_main && cp -r "$SRC"/. ~/pb_main/ && cd ~/pb_main/test || exit 1
find .. -name '*.sh' -exec sed -i 's/\r$//' {} + 2>/dev/null
: > ~/pb_each.tsv; mkdir -p ~/pb_out
for f in test_*.py test_*.sh; do
  case $f in *.py) c=python3;; *) c=bash;; esac
  s=$(date +%s); timeout 240 $c "$f" > ~/pb_out/$f.txt 2>&1; rc=$?
  printf '%s\t%s\t%s\n' "$f" "$rc" "$(( $(date +%s)-s ))" >> ~/pb_each.tsv
done
echo done > ~/pb_done
