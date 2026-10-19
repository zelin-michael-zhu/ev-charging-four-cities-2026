# Cleaned data dictionary

This independent derivative was prepared on **2026-10-19** from the four-city dataset released by **Yu ruotao** on Figshare. Original attribution and the **CC BY 4.0** data license are retained. This cleaning version should be distinguished from the original author's release.

Source: [Figshare version 1](https://doi.org/10.6084/m9.figshare.32917595.v1), published 2026-07-08; [upstream repository](https://github.com/yuruotao/chongqing_charging_data). Suggested source citation: ruotao, Yu (2026). *A spatiotemporal dataset of electric vehicle charging station utilization in four major Chinese cities*. Figshare. Dataset. DOI: 10.6084/m9.figshare.32917595.v1.

Changes in this derivative include rectangular hourly panels, explicit eligibility masks and quality flags, source-clock handling, and restricted station metadata. The derivative version is `2026-10-19-derived-v1`.

## Archive layout and grain

Each `cleaned-{city}.tar.gz` contains exactly these root-level files:

- `panel.npz`: dense arrays with separate data and eligibility masks.
- `panel.parquet`: long-form station-hour records.
- `station_quality.parquet`: descriptive station-level coverage and continuity.
- `station_meta.csv`: UTF-8 station metadata restricted to the fields below.

There is no extra city subdirectory inside an archive. Extract each archive into its own city directory. Per-file and per-archive bytes and SHA256 hashes are in [cleaned_manifest.json](../data/cleaned_manifest.json).

The grid has **T = 792** nominal hourly rounds from **2026-01-29 00:00 inclusive to 2026-03-03 00:00 exclusive**, interpreted as Asia/Shanghai (UTC+08:00). N is the source catalog size for that city. All catalog identifiers remain in the rectangular files, including stations with no eligible observations. A UID is a source record identifier; distinct UIDs have not been established to mean distinct physical facilities.

## NPZ fields

Load with `np.load(path, allow_pickle=False)`. Matrix axis 0 follows `time_slots`; axis 1 follows `station_ids`.

| Field | dtype | Shape | Meaning |
|---|---|---|---|
| `station_ids` | Unicode U24 | N | Source station UID, ordered by the source station catalog sorted by UID. |
| `time_slots` | Unicode U25 | 792 | ISO 8601 nominal collection-hour index with +08:00 offset. Not a synchronous citywide measurement. |
| `occupancy_rate` | float32 | T × N | `occupied / capacity` wherever `domain_valid`; NaN elsewhere. A finite value alone does not establish strict eligibility. |
| `valid` | bool | T × N | Primary strict public-scope observation mask. |
| `strict_valid` | bool | T × N | Alias equal to `valid`. |
| `basic_valid` | bool | T × N | Same public/clock/temporal checks as strict, but permits occupied + available < capacity. Equal to strict in these released data. |
| `domain_valid` | bool | T × N | Numeric/count/capture-domain check before public-scope and temporal exclusions. |
| `occupied` | int32 | T × N | AC occupied + DC occupied from the same source record. |
| `available` | int32 | T × N | AC available + DC available from the same source record. |
| `capacity` | int32 | T × N | AC pile count + DC pile count from the same source record. Use this dynamic denominator, not a metadata capacity. |
| `capture_time` | int64 | T × N | Parsed per-row source data-collection time as Unix seconds; -1 if missing/unparseable. Original naive times are interpreted as Asia/Shanghai. |
| `source_update_time` | int64 | T × N | Source Baidu update-time metadata as Unix seconds; -1 if unavailable/unparseable. Its telemetry-freshness meaning is not established. |
| `quality_flags` | uint16 | T × N | Bitwise OR of the diagnostic and eligibility flags below. |
| `ac_capacity`, `dc_capacity` | int32 | T × N | Reported counts of AC and DC piles, respectively. |
| `ac_occupied`, `dc_occupied` | int32 | T × N | Reported occupied AC and DC piles, respectively. |
| `frozen_state_run_hours` | uint16 | T × N | Length of the identical-six-count contiguous run containing the row, computed on the pre-temporal domain-valid grid. Descriptive and retrospective. |

Missing count cells may contain initialized zero. Invalid numeric records may contain integer-cast values or -1 sentinels. These cells do not establish observed zero demand. Only the corresponding mask authorizes use. Invalid domain values have NaN occupancy; public/clock-excluded domain-valid values can retain finite occupancy for auditability.

For a strict analysis:

```python
import numpy as np
z = np.load('panel.npz', allow_pickle=False)
eligible = z['valid']
occupancy = np.where(eligible, z['occupancy_rate'], np.nan)
capture = z['capture_time']
```

Forward-filled or interpolated values must not be relabeled as observed truth.

## Long-form Parquet

`panel.parquet` has T × N rows in time-major, station-minor order. Its fields are `station_id` (string), `time_slot` (timestamp[us, Asia/Shanghai]), `valid` and `basic_valid` (bool), `occupied`, `available`, `capacity` (int32), `occupancy_rate` (float32), `capture_time` (int64), and `quality_flags` (uint16). `time_slot` is the nominal collection round; use `capture_time` for observation-arrival and cutoff decisions.

The Parquet is a common-column view. Use NPZ for `domain_valid`, separate AC/DC counts, `source_update_time` and full unchanged-run diagnostics.

## Station quality fields

| Field | Definition |
|---|---|
| `station_id` | Join key to panel station UID and station metadata. |
| `basic_valid_hours`, `strict_valid_hours` | Number of eligible cells over all 792 nominal rounds. |
| `basic_coverage`, `strict_coverage` | Eligible hours divided by 792; missing source rounds remain in the denominator. |
| `longest_basic_valid_run_hours`, `longest_strict_valid_run_hours` | Maximum contiguous sequence of valid nominal hourly cells. A missing or invalid round breaks a run. |
| `longest_identical_state_run_hours` | Longest identical-six-count run on the pre-temporal domain-valid grid. |
| `capacity_change_events` | Adjacent pre-temporal domain-valid rounds whose AC or DC capacity differs. |
| `repeated_capture_timestamps` | Number of rows flagged as repeating the previous available source capture timestamp for that station. |
| `constant_occupied_trace` | True if occupied counts under the strict mask have zero standard deviation. This does not imply a constant occupancy ratio when capacity changes. False can also occur when there are no eligible observations. |

These are full-window descriptive summaries. They are not prospectively available covariates or recommended filters for a future prediction test.

## Restricted station metadata

Only these original audited fields are included in `station_meta.csv`:

| Field | Meaning |
|---|---|
| `station_id` | Source UID used for joining. |
| `name` | Source public charging-station name. |
| `latitude`, `longitude` | Source coordinates. The coordinate reference system was unspecified; source is Baidu Maps. Do not assume WGS84 without verification. |
| `ac_pile_count`, `dc_pile_count` | Source metadata AC/DC pile counts. These may summarize later records and are not a substitute for same-record panel capacity. |
| `city` | One of beijing, shanghai, shenzhen, chongqing. |
| `coordinate_reference_system` | Preserved explicit note about unresolved source coordinate semantics. |

Telephone, address and unrelated metadata columns are omitted. The retained metadata values carry the same upstream CC BY 4.0 attribution. The archive members are limited to the four data files listed above.

## Quality flags

A cell can have several flags. Test a flag with `(quality_flags & bit) != 0`.

| Bit value | Name |
|---:|---|
| 1 | `missing_snapshot_or_station` |
| 2 | `numeric_missing_or_noninteger` |
| 4 | `negative_count` |
| 8 | `zero_capacity` |
| 16 | `count_exceeds_capacity` |
| 32 | `closed_or_private_status` |
| 64 | `capture_unparseable` |
| 128 | `capture_clock_mismatch` |
| 256 | `repeated_capture_timestamp` |
| 512 | `frozen_state_48h` |
| 1024 | `capacity_changed` |
| 2048 | `identical_nonconstant_trace_candidate` |
| 4096 | `bulk_reporting_failure` |
| 8192 | `occupied_plus_available_less_than_capacity` |
| 16384 | `repaired_csv_record` |
| 32768 | `duplicate_station_hour` |

The exclusion bitmasks are **95** for domain, **4607** for basic, and **12799** for strict. See [data_quality.md](data_quality.md) for exact rules and limitations. Unchanged-state, capacity-change, cloned-trace, repaired-record and duplicate-UID diagnostic flags do not independently exclude an otherwise eligible retained row.
