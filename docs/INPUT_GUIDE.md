# Using your own isolates: sample sheet, folders, quick test

This guide is for you if you sequenced the isolates yourself and want PlasBench to benchmark plasmid tools on them. You do not need to know the file layout in advance: point PlasBench at the folder where your files are, and it finds what it needs, tells you what it cannot use and why, and repairs what it safely can.

Everything here is also in the window: **plasbench ui** then **Your own isolates**.

## The short version

1. **Get the sheet** (only if you want to write it yourself): `plasbench intake template local --out config/local.tsv`, or press **Download template** in the window.
2. **Find your files:** `plasbench intake scan /path/to/your/folder` (the window: **Find my files**, then choose the folder). Nothing is copied or changed.
3. **Place them:** `plasbench intake stage /path/to/your/folder`. This copies (or links) the files to where PlasBench expects them and writes the sheet.
4. **Quick test:** `plasbench intake check`. It opens every file the way a run will and says pass, warning or fail for each thing. Add `--fix` to repair what can be repaired.
5. **Decide the one thing only you can decide:** which sequences of the reference are plasmids (see [truth-review](#truth-review)).
6. **Run:** the command printed at the end of the check.

## What you need for each isolate

| Item | Needed for | Notes |
|---|---|---|
| Paired Illumina reads: two files (read 1 and read 2) | everything | gzip-compressed `.fastq.gz` or `.fq.gz`; uncompressed files are compressed for you |
| A **complete** reference genome of the **same isolate**: the chromosome and each plasmid as separate closed sequences, in one FASTA file | a scored benchmark | a set of unjoined contigs is not a reference; a related strain is not a reference |
| Which reference sequences are plasmids | a scored benchmark | a truth table, or an NCBI sequence report; PlasBench drafts the table from the FASTA headers and asks you about anything the headers do not say |
| The organism name | some tools (they only run for organisms they have a database for) | read from the FASTA header and shown as a guess to confirm |

Without a reference the isolate is still useful: PlasBench reconstructs its plasmids but cannot score them (`assembly_accession` is `NA`).

## How files are recognised

* **Read pairs:** `name_1.fastq.gz` + `name_2.fastq.gz`, `name_R1.fastq.gz` + `name_R2.fastq.gz`, or Illumina's `name_S1_L001_R1_001.fastq.gz` + `..._R2_001...` (also `.fq`, and `.` or `-` instead of `_`). Several lanes of one isolate are joined into one pair.
* **Isolate name:** the start of the read file name. When that is generic (`reads`, `sample`, `raw`), the name of the folder is used instead, so `isolates/KP01/reads_R1.fastq.gz` is isolate `KP01`.
* **Which FASTA is whose reference:** by name (`KP01.fna` for `KP01`), by folder (a FASTA in the isolate's own folder), or because it is the only isolate and the only FASTA. PlasBench shows how sure it is (`confident` or `likely`) and why. If two isolates could own the same file it gives it to **neither** and asks you to name it after its isolate.
* **Labels:** a `truth.tsv` or `<isolate>.truth.tsv` beside the reference, or an NCBI `sequence_report.jsonl`.
* Folders are searched three levels down (`--depth` changes that). Hidden folders are skipped.

## What PlasBench will not do

It will not decide which sequences are plasmids. Those labels are the ground truth every score is judged against, and a plausible guess there would quietly corrupt every number. A header that says "plasmid" or "chromosome" is used; anything else is left as `REVIEW`, and the run refuses to start while any `REVIEW` remains.

It will not change your original files. Everything is copied or linked into the isolate's own folder; repairs act on those copies.

## What the quick test checks

| Check | Why it matters |
|---|---|
| Both read files open and look like FASTQ | a damaged or wrong file fails hours into a run otherwise |
| Mates pair up: same read names, same order, same count | mismatched mates give a worse assembly, so the benchmark would measure the damage, not the tools |
| The reads are short reads | long reads need the hybrid route |
| The reference opens, is DNA, has unique sequence names and is a finished genome | scoring matches tool output to reference sequences by name |
| The truth table matches the reference: every sequence labelled exactly once, spelled exactly as in the FASTA | a mistyped name silently scores as a plasmid nobody recovered |
| **The reads come from the reference's isolate** | the check no file name can make: 21-letter words from a sample of the reads are looked up in the reference. Reads of that isolate match almost completely (pass at 80% or more); a close relative matches partly (warning); a different organism hardly at all (fail) |

The last check takes a few seconds and needs no extra software. Use `--fast` to skip it.

## What "Fix" repairs, and what it leaves to you

`plasbench intake check --fix` (the window: **Fix what can be fixed**) repairs only what has one right answer:

* a read file with a `.gz` name that is plain text: compressed;
* reads that are there under other names: correctly named copies are made (originals kept);
* a missing truth table: drafted from the FASTA headers (undecided sequences marked `REVIEW`);
* a truth table with wrong capitals in an id, stray spaces or Windows line endings: corrected; a reference sequence missing from the table: added as `REVIEW`;
* the template's `EXAMPLE_` row in the sheet: removed.

Everything else needs a decision or a different file, and the check says exactly what to do.

## If you see ...

Each message the scan or the check can show has a code and a section here. "Fix" says whether the repair button handles it.

### reads-not-gzip <a id="reads-not-gzip"></a>
**A read file has a .gz name but is not compressed.** The name says compressed, the content is plain text. *Fix: yes.* By hand: `gzip -c file.fastq > file.fastq.gz`.

### reads-misnamed <a id="reads-misnamed"></a>
**The read files have different names from the ones the sheet expects.** The run looks for `<sra_run>_1.fastq.gz` and `<sra_run>_2.fastq.gz` in the isolate's folder. *Fix: yes* (makes correctly named copies). By hand: rename the two files, or change the `sra_run` column to the shared start of their names.

### reads-missing <a id="reads-missing"></a>
**A read file is missing.** *Fix: no.* Put both files in `data/<sample_id>/` or run `plasbench intake stage <your folder>`; check that `sra_run` in the sheet matches the file names.

### reads-empty <a id="reads-empty"></a>
**A read file is empty.** Usually an interrupted copy or download. *Fix: no.* Copy it again and compare the size with the original.

### reads-corrupt <a id="reads-corrupt"></a>
**A read file is damaged or is not FASTQ.** *Fix: no.* Test with `gzip -t file.fastq.gz`; an error means it was cut short, so copy or download it again. If it opens but is not FASTQ it is the wrong file.

### reads-mates <a id="reads-mates"></a>
**Read 1 and read 2 do not match.** The two files must be the same library, the same reads in the same order. *Fix: no.* Re-copy both from the sequencer output. From SRA, re-extract with `fasterq-dump --split-files <accession>`. Never pair files only because their names look alike.

### reads-long <a id="reads-long"></a>
**These are long reads, not paired short reads.** The short-read route needs paired Illumina reads. *Fix: no.* Long reads belong to the self-built hybrid route (README, Route C). Do not rename them to `_1`/`_2`.

### reads-unpaired <a id="reads-unpaired"></a>
**A read file has no mate.** PlasBench needs paired-end reads. *Fix: no.* Find the other file, or leave the isolate out.

### folder-missing <a id="folder-missing"></a>
**The isolate's folder does not exist.** *Fix: no.* Run `plasbench intake stage <your folder>`, which creates it.

### reference-missing <a id="reference-missing"></a>
**A scored isolate has no reference.** *Fix: no.* Put the complete genome in the isolate's folder as `reference.fna`. With no complete genome, set `assembly_accession` to `NA`: the isolate is reconstructed but not scored.

### reference-unreadable <a id="reference-unreadable"></a>
**The reference cannot be read as FASTA.** A FASTA file starts with a line beginning `>`. *Fix: no.* Open it in a text editor: empty or starting with anything else means the wrong file or a bad copy.

### reference-duplicate-ids <a id="reference-duplicate-ids"></a>
**Two reference sequences have the same name.** Scoring matches tool output to sequences by name. *Fix: no.* Edit the FASTA headers so each first word is different and keep `truth.tsv` in step.

### reference-protein <a id="reference-protein"></a>
**The reference holds protein, not DNA.** *Fix: no.* Use the genome FASTA (`.fna`), not the protein FASTA (`.faa`).

### reference-draft <a id="reference-draft"></a>
**The reference looks like a draft assembly** (many contigs named `NODE_`, `contig` or `scaffold`). A benchmark's truth must be complete: a tool cannot be judged on a plasmid nobody assembled. *Fix: no.* Use a hybrid or long-read assembly, or run the isolate reads-only.

### reference-size <a id="reference-size"></a>
**The reference size is unusual** (outside 0.3-15 million bases). *Fix: no.* Check it is not a plasmid-only or phage file. If it is the right genome, ignore the note.

### reference-ambiguous <a id="reference-ambiguous"></a>
**More than one reference could belong to this isolate**, or one FASTA fits several isolates. PlasBench will not pick. *Fix: no.* Name each reference after its isolate (`KP01.fna`) or put it in that isolate's folder, then scan again.

### reference-wrong-isolate <a id="reference-wrong-isolate"></a>
**The reads do not match the reference.** Scores mean something only if the reference is the genome of the isolate the reads came from; a relative does not count. *Fix: no.* Find the right reference (check sample names against the lab record). With only the reads, run the isolate reads-only.

### truth-review <a id="truth-review"></a>
**Some sequences are still marked REVIEW.** *Fix: no, because this is the one decision that is yours.* Open **Label sequences** in the window (it shows each sequence, its length, its FASTA header and what the header says), or edit `data/<sample_id>/truth.tsv`, and set each to `PLASMID` or `CHROMOSOME`. Never infer the type from size.

### truth-missing <a id="truth-missing"></a>
**There is no truth table.** *Fix: yes* (a draft is written from the FASTA headers; `REVIEW` marks what they do not say).

### truth-mismatch <a id="truth-mismatch"></a>
**The truth table does not match the reference.** Every reference sequence needs exactly one row, spelled as in the FASTA, typed `PLASMID` or `CHROMOSOME`. *Fix: partly* (capitals, spaces, line endings, missing rows added as `REVIEW`). Duplicate rows and invented ids you must remove by hand.

### truth-no-plasmid <a id="truth-no-plasmid"></a>
**The truth has no plasmids.** Nothing can be recovered, so recall is undefined for this isolate. *Fix: no.* Keep it if it is a genuine plasmid-free control; otherwise check the labels.

### sample-id-unsafe <a id="sample-id-unsafe"></a>
**The sample name has characters that are not allowed.** Use letters, digits and `. _ -` only; it becomes a folder name. *Fix: no.* Rename the isolate in the list before staging.

### sheet-example <a id="sheet-example"></a>
**The sheet still has the template's example row.** *Fix: yes.* Or delete the `EXAMPLE_` line.

### long-reads-info <a id="long-reads-info"></a>
**Long-read files were found.** Not an error. They are not staged here: the self-built hybrid route is set up by hand (README, Route C).

## The sample sheet, column by column

```
sample_id    assembly_accession    sra_run    organism    gram_group    sample_origin    collection_country    source_study
```

| Column | Meaning |
|---|---|
| `sample_id` | A short name: letters, digits and `. _ -` only. It becomes `data/<sample_id>/`. |
| `assembly_accession` | `LOCAL` when you supply the reference (scored); `NA` for reads only (reconstructed, not scored). |
| `sra_run` | The start of the read file names: `<sra_run>_1.fastq.gz` and `<sra_run>_2.fastq.gz`. For your own data it is not an SRA accession; use the sample name. |
| `organism` | Genus and species. Some tools skip isolates whose organism they have no database for. |
| the rest | Optional notes that are carried into the report. |

Columns are separated by a **tab**. Lines starting with `#` are ignored. A public NCBI cohort uses a different, longer sheet: `plasbench intake template cohort`.

## Where each file ends up

```
data/<sample_id>/
    <sra_run>_1.fastq.gz      read 1
    <sra_run>_2.fastq.gz      read 2
    reference.fna             the complete genome (scored isolates only)
    truth.tsv                 PLASMID / CHROMOSOME for each reference sequence
    sequence_report.jsonl     optional NCBI report that replaces truth.tsv
```
