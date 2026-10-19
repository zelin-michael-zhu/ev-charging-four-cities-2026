# v1.0.0 — Four-city EV charging data (2026)

Unofficial mirror of Yu ruotao’s original Figshare dataset (CC BY 4.0), plus an independently cleaned derivative prepared on 2026-10-19.

Original source: https://doi.org/10.6084/m9.figshare.32917595.v1

## Downloads

- Original `data.zip`: concatenate `data.zip.part01` through `part04` in order; the assembled archive is byte-identical to the official 4,547,739,657-byte file.
- Cleaned data: one `cleaned-CITY.tar.gz` per city, containing NPZ/Parquet panels, station quality and minimal metadata.
- SHA256SUMS.txt and releases.json provide exact sizes/checksums. The `data.zip` line in SHA256SUMS refers to the reconstructed archive.

Common window: 2026-01-29 through 2026-03-02, 792 nominal hourly rounds. Strict public-cohort masks retain 17,998,928 valid station-hours. Missing reports are not interpolated or zero-filled. Use the validity masks and actual row capture times.

The raw archive is unchanged. The cleaned derivative adds masks, same-row occupancy ratios and a nominal hourly grid; unrelated station metadata is excluded. This is an independent derivative and does not imply the original creator’s endorsement. Data remain CC BY 4.0; new download/verification code is MIT.

Quick start from the repository: `python scripts/download_data.py --city beijing --extract`. See the repository README for source attribution, schema and quality limitations.
