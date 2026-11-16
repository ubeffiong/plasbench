# PlasEval-paper E. coli bins (53 isolates)

The bins in `bins/` are the data behind the PlasEval paper, unchanged:

> Mane A, Sanderson H, White AP, Zaheer R, Beiko R, Chauve C. *PlasEval: a framework for comparing and evaluating plasmid detection
> tools.* BMC Bioinformatics 2024;25:365. doi: [10.1186/s12859-024-05941-0](https://doi.org/10.1186/s12859-024-05941-0)
>
> Data: Zenodo [10.5281/zenodo.10785150](https://doi.org/10.5281/zenodo.10785150) (file `PlasEval_input.zip`), licence **CC BY 4.0**.
> The isolates are from Saskatchewan broiler farms: Sanderson H, Nnajide C, McCarthy M, Singh R, Rubin J, Dillon J-A, White A.
> *Hybrid genome assemblies of 245 avian and broiler barn environment-associated Escherichia coli strains isolated from Saskatchewan
> broiler farms.* Microbiol Resour Announc 2023;12:e0011023. doi: 10.1128/mra.00110-23 (BioProject PRJNA912639).

For each of the 53 isolates there is a folder with `ground_truth_bins.tsv` and the bins that four tools predicted on the isolate's
short-read assembly (`mob_recon_bins.tsv`, `hyasp_bins.tsv`, `gplas2_bins.tsv`, `plasbin_flow_bins.tsv`). Every file has the
columns `plasmid`, `contig`, `contig_len`. Contig ids are those of the isolate's short-read (Unicycler) assembly, so truth and
tools share one contig universe, which is what the PlasEval dissimilarity needs.

The cohort sheet for these isolates, with the accessions from the paper's `Ecoli_samples.csv`, is
[`../plaseval-ecoli53.tsv`](../plaseval-ecoli53.tsv). `python/plaseval_replication.py` scores these bins with PlasBench; see
`docs/PLASEVAL_REPLICATION.md`. Nothing is re-run: the tools' predictions are the paper's.
