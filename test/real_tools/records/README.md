# Real-tool check records

`.github/workflows/real-tools.yml` writes one record file per tool here when it runs the real binary on a known input and the output validates
(`python/database_provenance.py` and `adapters/REGISTRY.md` refer to these records as the evidence for `real_binary_checked`).

**No record has been committed yet.** Until a record exists for a tool, that tool is not `real_binary_checked`, whatever the registry says about its adapter:
13 tools are exercised only against stand-ins. (Audit finding AU-046, 17 November 2026.)
