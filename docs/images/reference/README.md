# Reference figures (local only)

Four published figures were collected as **design references** for the report. They are third-party material, so the image files are **not committed** (`*.jpg` in this folder is
gitignored) and are not part of the release archive. Keep your own copies here (`1.jpg` to `4.jpg`); this README, which is tracked, says what each one is for.

| File | What it shows | What PlasBench takes from it | Planned in |
|---|---|---|---|
| `1.jpg` | A circular map of one plasmid: gene arrows labelled by name, concentric rings for related plasmids, scale ticks, and brackets over multi-resistance regions (MRR I, MRR II) | Resistance-region brackets over clustered AMR genes on the plasmid map; homologous-plasmid rings; gene labels | D6 (`python/report_maps.py`) |
| `2.jpg` | Two BRIG-style maps: GC content and GC skew rings and one identity ring per comparison plasmid with a 100% / 70% / 50% identity legend | An identity ring per tool coloured by identity band (100 / 70 / 50%) beside the existing GC content and skew rings; a legend printed with the ring | D6 (`python/report_maps.py`) |
| `3.jpg` | (a) a heatmap of methods by metrics with the value in every cell and a colour bar; (b) a 3D scatter of true and false positives (coverage against sequence and taxonomic counts, colour = normalised score) | (a) a numeric tool x metric heatmap per task; (b) a 3D scatter of per-prediction true and false positives | D1 (`report_fig_heatmap.py`), D7 (`viz3d_*`) |
| `4.jpg` | A radar chart comparing methods on accuracy, sensitivity, specificity, AUC, memory and runtime | A tool performance fingerprint per task (detection, sequence recovery, binning, reconstruction, efficiency), drawn from the metric registry | D2 (new figure, registry-driven) |

The plan is in the project's release notes for v0.4.0; each figure is added by extending the existing section rather than creating a parallel one (see `docs/SCIENTIFIC_GUIDE.md`,
section 13.3, for the report as built).
