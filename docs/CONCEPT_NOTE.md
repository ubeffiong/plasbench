# Concept Note: PlasBench

## A reproducible benchmark for trustworthy plasmid research and antimicrobial-resistance surveillance

**Project name:** PlasBench (Plasmid Benchmarking Platform)  
**Project type:** Open research software and capacity-strengthening initiative  
**Primary users:** Microbiology and genomics researchers, public-health laboratories, universities, sequencing centres, antimicrobial-resistance (AMR) programmes, and research funders  
**Geographic focus:** Global, with deliberate relevance to African and other under-represented research settings  
**Status:** Open-source, early implementation; suitable for phased validation and cohort expansion

## Executive Summary

Antimicrobial resistance is increasingly driven by plasmids: small, transferable pieces of DNA that can carry resistance and virulence genes between bacteria. Laboratories can now generate bacterial genome data more readily than ever, but an important practical question remains difficult to answer: **which software method most accurately reconstructs plasmids from routine sequencing data?**

PlasBench is an open, reproducible platform designed to answer that question transparently. It evaluates plasmid-reconstruction methods against a trusted complete genome from the *same bacterial isolate*. Instead of relying on claims from individual software packages, PlasBench applies one consistent assessment method to all tools and produces an understandable report showing accuracy, limitations, data quality, uncertainty, and downloadable evidence.

The platform is intended to help researchers and programmes make better-informed method choices before using results for AMR research, outbreak investigation, One Health surveillance, or scientific publication. It is not a diagnostic device and does not replace laboratory confirmation. Its value is to make analytical choices visible, comparable, and reproducible.

Investment in PlasBench would support three connected needs:

- A reliable public benchmark resource for plasmid reconstruction.
- Inclusion of diverse bacterial isolates, especially from African clinical, veterinary, food, and environmental settings that are presently under-represented in method evaluations.
- Sustainable local capacity to run, audit, adapt, and contribute to genomic AMR research without dependence on closed commercial systems.

## The Problem

Plasmids matter because they can move important genes between bacteria. A plasmid carrying resistance to last-line antibiotics can spread within hospitals, communities, animals, food systems, or water environments. Understanding whether resistance genes are located on plasmids, and whether those plasmids are correctly reconstructed, is therefore central to AMR research and surveillance.

Most bacterial sequencing projects use short-read data because it is accessible and affordable. Short reads are powerful, but plasmids are difficult to reconstruct from them: plasmids often contain repeated sequences, vary in copy number, and may share sequence with chromosomes or other plasmids. Different software tools can therefore produce different answers from the same sample.

Researchers currently face four connected challenges:

- **No single universally trusted tool.** Different tools have different strengths, assumptions, and output formats.
- **Inconsistent evaluation.** Tool developers and individual studies often use different datasets and different definitions of success, making results hard to compare.
- **Limited representation.** Public evaluations commonly over-represent a small number of organisms, regions, and well-resourced laboratories. African clinical and environmental isolates are often absent or insufficiently documented.
- **Weak reproducibility.** Results may omit exact tool versions, reference quality, input provenance, parameter settings, runtime, and failure information. This makes it difficult to reproduce or trust a ranking.

These gaps can lead to overconfident conclusions. A method that appears accurate in one dataset may perform poorly with a different species, plasmid size, sequencing depth, or local epidemiological context.

## The Proposed Solution

PlasBench is a transparent evaluation framework that compares plasmid-reconstruction tools using the same biological truth source and the same performance measures.

For each bacterial isolate, PlasBench uses:

1. Routine paired short-read sequence data, typically Illumina reads.
2. A complete long-read or hybrid reference genome from that same isolate as the trusted comparison standard.
3. Several plasmid-reconstruction methods run under documented conditions.
4. A common scoring approach that measures how accurately each method recovers known plasmid sequence while avoiding chromosome misclassification.

The platform then produces an interactive HTML report, machine-readable tables, a reproducibility manifest, logs, and downloadable outputs. A researcher can see not only which method ranked highest overall, but also whether performance changes by species, sample source, sequencing depth, plasmid characteristics, tool version, or data-quality category.

## What PlasBench Delivers

### Evidence for method selection

PlasBench gives laboratories a structured way to choose an appropriate plasmid-reconstruction workflow for their own research question and sample type. It measures recovery of expected plasmid sequence, incorrect chromosome assignment, and balance between these outcomes.

### A clear, auditable report

Each run produces a self-contained dashboard that includes:

- An overall leaderboard and per-sample results.
- Plain-language interpretation of key measures, including precision, recall, F1 score, plasmid recovery, uncertainty intervals, and tool failures.
- Colour-coded performance indicators, charts, filters, and drill-down views.
- Sample and tool metadata, parameters, versions, checksums, runtime information, and available database/container identity.
- A file explorer for downloading score tables, logs, plots, prediction files, and the run manifest.

### Fair comparison across tools

Different tools describe plasmids differently. Some label pieces of an assembly as plasmid; others attempt to build plasmid sequences directly. PlasBench translates their outputs to a common comparison basis before scoring them, making the comparison more defensible than a simple count of reported sequences.

### Cohort curation safeguards

PlasBench does not treat every public genome record as reliable truth. A released benchmark cohort must meet strict requirements: a complete plasmid-containing reference, explicit evidence of long-read or hybrid reference technology, matched paired short-read data, and matching sample/project identifiers. Candidates that do not meet these rules are retained with rejection reasons rather than quietly included.

### Open access and flexible deployment

The software can run locally on Linux or Windows Subsystem for Linux, in Docker containers, and can be packaged for shared platforms such as Galaxy. Users can analyse their own valid cohorts; PlasBench is not restricted to a predefined list of bacteria or countries.

## How PlasBench Works

PlasBench is a structured research workflow, not a black box. It takes a set of carefully selected bacterial isolates, applies the same comparison process to each participating method, and produces evidence that can be inspected, reproduced, and shared.

### What PlasBench Needs

For each isolate, PlasBench needs two linked forms of sequence data:

1. **Paired short-read files:** usually Illumina FASTQ files. These routine, relatively affordable reads are what the tools being compared use to attempt plasmid reconstruction.
2. **A complete reference genome from the same isolate:** normally made using Oxford Nanopore, PacBio, or a hybrid long-read/short-read approach. This reference is the trusted answer against which the short-read reconstruction is evaluated.

The reference and reads must genuinely come from the same isolate. PlasBench also needs basic sample information such as organism, source, location, sequencing technology, and public accession identifiers where data are downloaded from public repositories. This allows results to be interpreted by cohort, geography, organism, and data quality rather than as a single unexplained score.

### The Core Workflow

```text
Select and verify matched data
          |
          v
Prepare short reads and reference truth
          |
          v
Build a short-read assembly
          |
          v
Run several plasmid-reconstruction methods
          |
          v
Compare each prediction to the complete reference
          |
          v
Aggregate, interpret, and publish an interactive report
```

#### 1. Select and verify matched data

Researchers either provide their own data or select public data from sources such as NCBI and the Sequence Read Archive. PlasBench checks that the reference is complete, contains declared plasmid sequences, has documented long-read or hybrid evidence, and is linked to a paired short-read run from the same sample and study. This prevents a comparison based on unrelated or incomplete records.

#### 2. Prepare the data and define the truth

The workflow checks and trims short reads to reduce low-quality sequence. It uses the complete reference to identify which DNA sequences are plasmids and which are chromosomes. This creates a transparent comparison standard without using a tool under evaluation to define its own success.

#### 3. Build a short-read assembly

The routine short reads are assembled into longer sequence fragments. This is the realistic starting point for many laboratory workflows and gives each plasmid method the type of input it would receive in normal practice.

#### 4. Run plasmid-reconstruction methods

PlasBench runs each selected method under documented settings. It records whether a tool completed, failed, was skipped, or produced an interpretable output. Tool-specific output is converted into a common comparison format so that methods are evaluated fairly even when they describe plasmids differently.

#### 5. Compare predictions to the trusted reference

Each predicted plasmid sequence is compared with the complete reference. The workflow asks two practical questions: how much known plasmid sequence was recovered, and how much chromosome sequence was incorrectly called a plasmid. It also examines recovery of individual plasmids, plasmid bins where available, circular plasmids, and AMR genes when those annotations are provided.

#### 6. Aggregate and communicate findings

Results from all isolates and tools are combined into an interactive report. The report shows average performance, variation between samples, uncertainty, tool failures, data provenance, and downloadable supporting files. Users can filter evidence and inspect an individual sample instead of relying only on an overall ranking.

### Main Components

| Component | Plain-language role |
|---|---|
| Cohort validator | Screens candidate samples and verifies that the short reads and complete reference belong together. |
| Data preparation | Downloads or accepts local inputs, checks read quality, and prepares files for analysis. |
| Truth builder | Uses the complete reference to label known plasmid and chromosome sequences. |
| Assembly stage | Reconstructs longer sequence fragments from routine short-read data. |
| Tool adapters | Standardise outputs from different plasmid methods so they can be compared on the same basis. |
| Scoring engine | Measures plasmid recovery, chromosome contamination, balance of performance, and related biological indicators. |
| Report and provenance engine | Produces tables, charts, an interactive dashboard, logs, and a record of data sources, versions, settings, and runtime. |

### Third-Party Tools Used Within the Workflow

PlasBench coordinates established bioinformatics tools rather than attempting to replace them. The exact set can be selected for a particular run and all available versions are recorded in the final report.

| Tool or service | Role in PlasBench |
|---|---|
| NCBI Datasets, NCBI Assembly, and Sequence Read Archive | Public sources for reference genomes, reads, and deposited sample metadata. |
| fastp | Checks and improves raw short-read quality before assembly. |
| SPAdes or Unicycler | Builds a conventional short-read assembly. |
| MOB-suite (`mob_recon`) | Identifies and reconstructs likely plasmid sequence from assemblies. |
| Platon | Classifies assembled sequences as likely plasmid or chromosome. |
| plasmidSPAdes | Attempts plasmid-focused reconstruction from short reads. |
| gplas/gplas2 modes | Optional graph-based plasmid reconstruction modes when a validated classifier input is available. |
| minimap2 | Aligns predicted plasmid sequences to the trusted complete reference for fair scoring. |
| seqtk | Optional, controlled read subsampling for sequencing-depth experiments. |
| Docker and Conda/Mamba | Optional reproducible software environments for local, server, or cloud deployment. |

Third-party tools remain independently developed software. PlasBench records their versions and settings, but a ranking applies only to the selected data, tool versions, and configuration; it is not a permanent universal claim that one method is always best.

### Required, Optional, And Extended Flows

**Required core flow**

- Prepare a valid sample sheet and matched data pair for each isolate.
- Run read preparation, assembly, selected plasmid tools, scoring, and report generation.
- Review the dashboard, score tables, tool-status table, and reproducibility manifest before interpreting a result.

**Optional flow: local data**

Institutions can supply their own FASTQ files and complete reference instead of downloading public data. This is useful for data that cannot be shared publicly, for new local sequencing projects, or for studies involving priority organisms not yet represented in a public cohort.

**Optional flow: selected methods**

Users may enable only the methods that are relevant and installed in their environment. This supports small pilot studies and allows a laboratory to add new methods as they become available, while keeping the common scoring method.

**Extended flow: depth-ladder experiment**

PlasBench can make controlled lower-depth copies of the same short-read data and repeat the benchmark. This shows how recovery changes with sequencing coverage and helps distinguish a weak method from a sample that simply has too little data.

**Extended flow: curated public cohort development**

Researchers can use the candidate-screening process to build a locally relevant cohort. Candidate records remain separate from released benchmark panels until their identity, source publication, sequencing evidence, and metadata have been reviewed.

**Extended flow: deployment and collaboration**

The same workflow can be run on a researcher laptop through WSL/Linux, an institutional server, a Docker-enabled environment, or a shared analysis platform such as Galaxy. This enables teaching, multicentre comparison, and repeatable analyses across sites.

### Outputs and How They Are Used

| Output | What it provides | Typical user |
|---|---|---|
| Interactive HTML dashboard | A visual, filterable summary with charts, colour cues, definitions, drill-downs, and links to downloadable evidence. | Researchers, supervisors, programme managers, funders |
| Tool leaderboard | A transparent comparison of average precision, recall, plasmid recovery, F1 score, uncertainty, and completion status. | Method-selection teams, manuscript authors |
| Per-sample score tables | Detailed results for every sample-tool pair, including recovery and contamination information. | Bioinformaticians, analysts, reviewers |
| Tool-status and log files | Clear evidence of completed, failed, skipped, or incomplete steps. | Analysts, technical support, quality-assurance teams |
| Provenance manifest | Input checksums, public accessions, versions, settings, run environment, timing, and output inventory. | Reproducibility reviewers, funders, publishers |
| Prediction and alignment files | The underlying sequence outputs and comparisons supporting each result. | Advanced researchers and method developers |
| Depth-ladder tables and plots | Evidence showing recovery versus sequencing coverage where this optional study is run. | Sequencing planners, grant teams, laboratory managers |

### Goals and Where PlasBench Can Be Used

PlasBench has five practical goals:

1. Help researchers choose an appropriate plasmid-reconstruction method for a defined study and dataset.
2. Improve the credibility and reproducibility of plasmid and AMR genomics research.
3. Build diverse, validated evidence that includes locally relevant organisms, sample sources, and geographies.
4. Strengthen capacity for transparent genome analysis in universities, reference laboratories, sequencing centres, and public-health programmes.
5. Provide funders and collaborators with visible, auditable evidence of how conclusions were generated.

It can be used in research projects, AMR surveillance research, One Health studies, postgraduate training, methods development, sequencing service quality assurance, publication preparation, and multicentre collaborations. It should not be used as a stand-alone clinical diagnostic or as conclusive proof of plasmid transmission without additional laboratory and epidemiological evidence.

## Who Benefits

**Researchers and postgraduate trainees** gain a repeatable framework for comparing methods, producing publication-ready evidence, and learning reproducible genomic practice.

**Public-health and AMR programmes** gain more transparent analytical evidence to support surveillance research, method harmonisation, and future guideline development.

**Sequencing centres and reference laboratories** gain a quality-assurance resource for evaluating pipelines before applying them at scale.

**Universities and African research institutions** gain an open platform that can be run with local infrastructure, adapted to locally relevant pathogens, and expanded through collaborative data curation.

**Funders and policy stakeholders** gain a measurable investment in open, reusable digital public infrastructure rather than a one-off analysis. The resulting cohorts, documentation, reports, and reproducibility records can support multiple studies over time.

## Scientific and Public-Health Relevance

PlasBench supports a One Health view of AMR. It can be used with bacterial isolates from people, animals, food, water, soil, and health-care environments, provided each sample has the required matched sequence evidence. This enables future questions such as:

- Which reconstruction methods are most dependable for high-priority bacterial pathogens?
- Does performance vary between clinical and environmental isolates?
- How much sequencing depth is needed before plasmid recovery becomes reliable?
- Which methods preserve separate plasmids rather than combining them or splitting them incorrectly?
- How reliably are plasmid-borne AMR genes recovered?

The platform does not claim that a computational prediction proves plasmid transmission or clinical risk. Rather, it provides the evidence base needed to select and interpret computational methods responsibly.

## Implementation Approach

### Phase 1: Consolidate the open platform

This phase maintains and tests the core software, documentation, containerised environment, automated reporting, and quality-control checks. It also establishes user support materials, example datasets, and clear boundaries around appropriate use.

**Outputs:** stable open-source release, installation guidance, user guide, test suite, reproducible execution environment, and interactive reporting template.

### Phase 2: Build a curated public benchmark cohort

This phase develops a released panel of approximately 40-60 rigorously verified isolates. The cohort will seek balance across major bacterial groups, plasmid profiles, read depths, and clinical/environmental/animal sources. It will deliberately pursue African representation without lowering data-quality criteria.

Each candidate will be screened for complete reference quality, long-read/hybrid evidence, exact read/reference linkage, metadata completeness, source publication, and collection context. Records that are promising but incomplete will remain clearly labelled as candidates rather than being promoted to the released cohort.

**Outputs:** versioned cohort, validation lock file, provenance records, curation protocol, release documentation, and a permanent DOI through an approved repository such as Zenodo.

### Phase 3: Comparative analyses and capacity strengthening

This phase runs the benchmark across the curated panel, undertakes controlled sequencing-depth analyses, evaluates current and emerging tools, and trains participating researchers to reproduce and extend analyses.

**Outputs:** comparative report, depth-versus-recovery findings, training materials, workshops or virtual clinics, contributed local cohorts, and manuscripts/policy briefs as appropriate.

### Phase 4: Long-term community stewardship

This phase establishes a transparent governance model for tool additions, cohort releases, issue reporting, data contributions, versioning, and reproducibility review.

**Outputs:** contributor guide, release schedule, advisory group, public roadmap, and sustainable maintenance plan.

## Expected Results and Indicators

Success should be assessed through both scientific quality and equitable use.

| Result area | Illustrative indicators |
|---|---|
| Reliable software | Versioned releases; passing automated tests; reproducible container/environment records; documented issue resolution |
| Quality benchmark data | Number of fully verified isolates; diversity by organism, geography, source, plasmid profile, and sequencing depth; proportion with complete provenance |
| Better research decisions | Number of studies/labs using PlasBench; documented tool-selection decisions; reports generated and shared |
| Capacity strengthening | Researchers trained; institutions able to run the workflow locally; contributed cohorts reviewed and reused |
| Open-science value | Public code, documentation, release DOI, reusable reports, citation/download metrics, and external contributions |
| Equity and representation | African and other under-represented isolates included only when evidence standards are met; partnerships contributing local expertise and metadata review |

## Data Quality, Ethics, and Responsible Use

PlasBench is designed around responsible handling of public genomic data and transparent limitations.

- It uses publicly available accessions or user-provided data with appropriate permission.
- It retains provenance, checksums, parameters, versions, and outputs to support reproducibility.
- It does not require patient-identifying information and should use de-identified metadata only.
- It does not make clinical diagnoses, recommend treatment, or replace laboratory confirmation.
- It does not claim biological matching solely from a database label; strict metadata checks are combined with curator review.
- It distinguishes verified released cohorts from candidate records and retains reasons why candidates were rejected.

For locally generated data, participating institutions should apply their own ethics approvals, data-sharing agreements, and national requirements before release or transfer.

## Key Risks and Mitigation

| Risk | Mitigation |
|---|---|
| Incomplete or mismatched public metadata | Strict eligibility rules, independent checks, curator review, and transparent rejection logs |
| Under-representation of African datasets | Active partnership-based curation, support for local data generation, and no dilution of standards merely to meet a quota |
| Rapid changes in bioinformatics tools | Plugin-based tool interface, version capture, repeatable test fixtures, and periodic benchmark updates |
| Compute and connectivity constraints | Local/offline-ready reporting, Docker support, scalable staged execution, and capacity-building guidance |
| Misinterpretation as a diagnostic tool | Prominent research-use limitations in reports, documentation, training, and dissemination materials |
| Long-term maintenance burden | Open governance, reproducible environments, documentation, community contributions, and targeted maintenance funding |

## Partnership and Governance Model

PlasBench should be developed as a collaborative public-good resource. A practical governance structure would include:

- A technical maintenance team responsible for releases, quality assurance, security updates, and user support.
- A scientific advisory group including microbiologists, genomic epidemiologists, bioinformaticians, and AMR specialists.
- Cohort curators with knowledge of sample provenance, sequencing technologies, and local context.
- Partner laboratories contributing validated data, use cases, and feedback.
- Funders and stakeholders receiving periodic progress reports against agreed indicators.

All significant cohort additions and method changes should be versioned and documented so that a published result can be traced to the exact data and software used.

## Resource Needs

The exact budget will depend on partnership scope and data availability. A fundable work plan should cover:

- Personnel for software maintenance, data curation, scientific review, and training.
- Compute and storage for downloading, assembling, benchmarking, and archiving sequence data.
- Long-read and short-read sequencing for priority local isolates where appropriate data do not exist.
- Workshops, mentorship, and collaboration with participating laboratories.
- Publication, repository/DOI, documentation, and community-engagement costs.

The most important investment is not only software development. It is the careful, documented curation of matched reference and read data, especially for diverse African clinical, veterinary, food, and environmental isolates.

## Sustainability and Scale

PlasBench is designed to remain useful beyond a single grant because it is open source, container-ready, and based on transparent data and method records. New tools can be added without changing the core comparison principle. New cohorts can be evaluated while preserving earlier releases. Institutions can run the software locally and retain full control of their data and outputs.

Over time, PlasBench can evolve into a shared evidence resource for plasmid reconstruction in AMR research, supporting regional networks, multicentre studies, postgraduate training, and reproducible publication standards. Its long-term value lies in enabling many groups to answer the same foundational question with comparable, auditable evidence: **which analytical method can be trusted for this dataset and purpose?**

## Funding Proposition

Support for PlasBench would create an open, practical, and equitable foundation for plasmid and AMR genomics. It addresses a clear evidence gap between the availability of bacterial sequence data and the confidence with which researchers can interpret plasmid results.

The proposed investment will deliver more than software: it will produce curated benchmark data, reproducible analysis records, researcher capacity, collaborative networks, and transparent evidence for method selection. By centring rigorous validation and meaningful representation, PlasBench can help ensure that advances in pathogen genomics are credible, reusable, and relevant to the settings most affected by AMR.

## Contact and Further Information

**Project lead:** Ubokobong Effiong  
**Email:** ubokobongokon@gmail.com | ueffiong@ihvnigeria.org  
**Institutional acknowledgement:** International Research Center of Excellence at the Institute of Human Virology Nigeria (IHVN). This acknowledgement does not imply institutional ownership, funding, endorsement, or approval unless formally confirmed by IHVN.  
PlasBench source code, technical documentation, demonstration workflow, and reproducibility materials are available at [github.com/ubeffiong/plasbench](https://github.com/ubeffiong/plasbench). The project team can tailor a work plan, budget, and partnership model to the priorities of a specific institution, funder, country programme, or regional network.
