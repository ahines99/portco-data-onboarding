# Public operational-data ingestion exercise

This exercise imports and profiles a bounded extract of real historical retail transactions.
It does not approve a mapping, generate certified financial metrics, or establish customer adoption.

## Source and attribution

Chen, D. (2015). **Online Retail** [Dataset]. UCI Machine Learning Repository.
[DOI: 10.24432/C5BW33](https://doi.org/10.24432/C5BW33).
The [official dataset page](https://archive.ics.uci.edu/dataset/352/online+retail) describes
transactions from a UK online retailer during 2010–2011 and declares a
[CC BY 4.0 license](https://creativecommons.org/licenses/by/4.0/).
The dataset's license is separate from this repository's MIT code license.

The reproducible input is the official archive, pinned to SHA-256
`f5385cbb54bbebf7196389109c6b0621faab0c304e3702548165e71c84aede8b`.
The script refuses a changed archive pending explicit source review. Large/raw files remain under
ignored `var/`; the committed evidence contains aggregate results and provenance only.

## Deliberate adaptation

- Select the first 10,000 transaction rows in worksheet order. This is chronological convenience
  sampling, not a representative random sample or an unseen financial-accuracy benchmark.
- Retain source field names for invoice, product, quantity, date, price and customer identifiers.
  Drop free-text product descriptions and country. Add the documented GBP currency and a
  cancellation flag derived from the source invoice prefix.
- Replace invoice/product/customer identifiers with deterministic SHA-256 pseudonyms using a
  public namespace. These are not a guarantee of anonymization: public identifiers can be guessed.
- Preserve missing customer IDs as SQL NULL, all cancellations, negative quantities and nonpositive
  prices. Do not silently remove inconvenient records to make the workflow appear clean.
- Preserve price decimal text from the workbook in `DECIMAL(38,18)`. The source includes binary
  spreadsheet-number serialization artifacts; the extract control sum deliberately retains them.
  Do not relabel that sum as recognized revenue, audited money, or an accounting ground truth.
- Verify imported row count, exact quantity-times-price sum, missing IDs, cancellation count and
  negative-quantity count against the prepared extract. Verify the profile row count separately.

## Reproduce

From a repository checkout with its frozen Python environment:

```text
uv run python -m scripts.public_retail_probe --download --archive var/public-data/online-retail.zip --out var/public-data/extract-10000 --state var/public-retail-state --report var/public-retail-report.json
```

Use new extract/state directories for each run. The fixed public download is about 24 MB.
The parser uses Python's standard library and operates only on the exact reviewed archive;
no spreadsheet library or new runtime dependency is installed.

The script uses the [CSV importer](CSV-SOURCE.md), then the normal source registration,
read-only adapter, connection validation and profiling workflow. It stops after schema profiling.
No reviewer token or human decision is used. Profile findings, raw extracts and source snapshots
remain local. The shareable report records only bounded aggregate measurements and provenance.

## Observed result

The initial local exercise successfully imported and profiled 10,000 rows and passed all six
aggregate control checks. The extract included 100 cancellation rows, 130 negative-quantity rows,
46 nonpositive-price rows and 2,291 missing customer IDs. These categories can overlap.
The observed dates span 2010-12-01 through 2010-12-05.

The final [machine-readable report](evidence/public-retail-profile.json) records source/extract
hashes, implementation hashes, execution provenance, measurements and the unapproved/unpublished
workflow state. This exercise closes the absence of any operational-input evidence at ingestion
and profiling scope. It does not close arbitrary-schema mapping, a live source-system connection,
financial certification, hosted production acceptance, or the [operator pilot](OPERATOR-PILOT.md).
