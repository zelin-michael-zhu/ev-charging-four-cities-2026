# Data quality and reuse limits

## Version and provenance

This is the **2026-10-19-derived-v1** independent cleaning of the original [Figshare dataset](https://doi.org/10.6084/m9.figshare.32917595.v1), retaining its **CC BY 4.0** attribution. It should be identified as an independent derivative when cited, alongside the original source citation in [data_dictionary.md](data_dictionary.md). The original archive is 4,547,739,657 bytes, with supplied and locally verified MD5 `1b7d7f2ba81f3b9d1b06d4d77a6533d9`. Source-data and code licensing should not be conflated.

The cleaned archives preserve the audited NPZ, long-form Parquet and station-quality Parquet bytes. Only station metadata is reduced to a field allowlist. No occupancy labels are interpolated, backfilled, forward-filled or replaced by model predictions.

## Counts and denominators

The common window is 2026-01-29 00:00 to 2026-03-03 00:00 exclusive, Asia/Shanghai, with **792 nominal hours** in each city.

| City | Catalog UIDs | Snapshot rounds | Domain-valid cells | Strict public-valid cells |
|---|---:|---:|---:|---:|
| Beijing | 9,068 | 759 / 792 | 5,038,641 | 4,070,648 |
| Shanghai | 13,265 | 766 / 792 | 7,371,864 | 6,095,332 |
| Shenzhen | 8,484 | 765 / 792 | 4,813,939 | 3,574,573 |
| Chongqing | 8,117 | 765 / 792 | 4,664,260 | 4,258,375 |

Across the cities: **38,934 catalog station identifiers**, **30,835,728 rectangular station-hour cells**, **21,888,704 domain-valid cells**, and **17,998,928 strict public-scope valid cells**. Strict coverage in the manifest uses all 792 × catalog-station cells as its denominator, not only hours with a file or stations that later become well observed.

The original archive also contains CSVs outside the main observation window. All 3,318 source CSV files contain 31,709,085 rows; 29,672,222 rows fall in the stated main window. The cleaned panels retain the main window. Distinct UIDs describe catalog records, not independently verified physical locations.

## Eligibility rules

1. **Domain validity** requires a source-catalog UID; finite, integer, nonnegative six-count values; positive total capacity; occupied + available not exceeding capacity separately for AC and DC; and a parseable capture timestamp. Missing files or stations remain invalid cells.
2. **Public-scope basic validity** also rejects explicit closed/private/in-construction statuses, capture clocks more than 90 minutes from the exact filename timestamp, subsequent repeated capture timestamps, and city-round bulk reporting failures.
3. **Strict validity** additionally requires occupied + available = capacity separately for AC and DC.

The saved masks satisfy `domain_valid == ((flags & 95) == 0)`, `basic_valid == ((flags & 4607) == 0)`, and `valid == strict_valid == ((flags & 12799) == 0)`. In this release basic and strict are elementwise identical: relaxing equality produces no additional usable rows. They are not independent replications.

The public-status exclusion pattern is `暂停|不对外|关闭|搬迁|在建|停业|未开放|未营业|停止|内部`. This includes “仅供内部使用”. Exclusion defines the public-use cohort and is not proof of erroneous telemetry. Blank or unknown status is retained, so eligibility does not independently prove public access.

A bulk reporting failure is a source round where at least 95% of reported stations have all six counts zero and the positive-capacity fraction is no more than 10% of that fraction in the first observed official-window snapshot. The reference is available at the start; it is not a full-window median. Subsequent repeated capture times are excluded. Unchanged occupied values with advancing capture clocks are not automatically stale.

## Missingness and timestamps

A nominal h:00 row indexes a collection round. Each station is sampled at its own source capture time, often several minutes after h:00. Rows do not represent a synchronous citywide state. A model or replay must not reveal a report before `capture_time` has arrived; the nominal grid alone is not a sufficient cutoff.

Missing hourly rounds remain in the grid. On 2026-02-18 each city has only the 23:00 source snapshot; one calendar day does not provide 24 valid hourly observations. The final seven nominal hours on 2026-03-02 are bulk-zero failures in Shanghai, Shenzhen and Chongqing. They remain excluded observations, not evidence of seven hours of zero occupancy.

Absent or invalid count cells can contain zero or -1 placeholders; consult masks. Conversely, `occupancy_rate` can be finite in a domain-valid cell excluded from the public/clock-valid cohort. Filtering only `isfinite(occupancy_rate)` changes the intended population.

Baidu update time is retained separately. Its meaning has not been established as charging telemetry freshness, a heartbeat, or the last occupancy change. Capture time is a recorded collection time, not field verification.

## Descriptive flags and future information

Constant and low-demand sites remain valid when their counts, clocks and access scope pass the rules. An unchanged state is flagged at a 48-hour run length but is not automatically deleted. It cannot alone prove a sensor freeze.

Unchanged-run length uses a forward/backward whole-run calculation, so an early row in a long run can already carry the 48-hour diagnostic flag. Identical-trace candidates and station-level coverage and continuity summaries also use the complete observation window. Do not use these retrospective summaries to select stations or create causal real-time features before a test period. Define prospective qualification from a historical warmup period instead.

The source station catalog and static metadata can reflect the full collection window. Do not assume all metadata capacities and site attributes were available at the first nominal round. Use contemporaneous observed capacity for occupancy and explicitly time-limit features.

## What the labels identify

The measured target is a map-platform report of occupied piles divided by reported capacity. It does not identify charging energy, completed transactions, unmet demand, queues, driver arrival failure, revenue, physical availability or an audited citywide demand measure. AC and DC counts are preserved separately because adding pile types does not establish an interchangeable charging service.

The observation period is 33 days in four cities. It does not by itself support annual-seasonality or nationally representative claims. Physical-site identity, coordinate reference system, platform status truth and source update-time semantics remain unresolved. New calendar dates and many rows do not remove these limits.

## Verification included with this publication

Packaging verifies masks against the documented flag bitmasks, reconciles city counts to the audited report counts, checks rectangular Parquet row counts and station-quality sums, preserves the three core cleaned files byte-for-byte, scans selected metadata fields for common credential patterns, and rereads every tar member to verify SHA256.

The metadata allowlist omits telephone, address and other unrelated fields. A pattern scan is not an exhaustive security audit. The data checks establish package integrity and documented eligibility; they do not establish on-site truth.

Use [cleaned_manifest.json](../data/cleaned_manifest.json) for all archive and file hashes and concrete NPZ schemas. See [data_dictionary.md](data_dictionary.md) for field meanings and safe mask use.
