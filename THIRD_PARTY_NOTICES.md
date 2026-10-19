# Sources, attribution and changes

## Original data

- Creator, as supplied by Figshare: **Yu ruotao**.
- ORCID: https://orcid.org/0009-0005-4887-2339
- Title: **A spatiotemporal dataset of electric vehicle charging station utilization in four major Chinese cities**.
- Version DOI: https://doi.org/10.6084/m9.figshare.32917595.v1
- Published: 2026-07-08.
- License: **Creative Commons Attribution 4.0 International**, https://creativecommons.org/licenses/by/4.0/ . The license reference is in `LICENSE`; the full terms are linked there.
- Original archive: `data.zip`, Figshare file ID 66387119, 4,547,739,657 bytes, MD5 `1b7d7f2ba81f3b9d1b06d4d77a6533d9`.
- Original project: https://github.com/yuruotao/chongqing_charging_data . Its README describes its code as MIT; this repository does not bundle that upstream code or apply that statement to the dataset.

The raw release parts concatenate to the exact original archive. Splitting is a transport operation; the source archive content is unchanged. Original public station metadata remains inside that source archive.

## Cleaned derivative

Prepared by the maintainer of `zelin-michael-zhu/ev-charging-four-cities-2026` on 2026-10-19. These files are independently processed derivatives, not an official corrected release from the original creator.

Changes include parsing raw station-hour reports, limiting the principal panel to the common 2026-01-29 through 2026-03-02 window, aligning to a complete nominal hourly grid, computing same-row occupancy ratios, adding validity/quality masks, and producing NPZ/Parquet tables. Strict public-cohort status and count/clock checks are documented separately. Missing labels remain unknown and are never interpolated into truth. Lightweight station metadata is restricted to analysis-relevant fields; telephone fields and unrelated metadata are omitted from cleaned downloads.

The derivative data are provided under CC BY 4.0 with original attribution and this modification notice retained. No physical ground truth or original-author endorsement is implied. The mirror maintainer does not claim authorship of the original observations.

## New tools and excluded material

The new standard-library download, checksum, archive-safety and testing utilities are licensed under `LICENSE-CODE` (MIT). No research-paper full texts, school documents, UrbanEV records or downstream FYP experiment outputs are included in this release.
