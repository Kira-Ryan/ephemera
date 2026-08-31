# P4 — What does the archive cost?

**Status:** desk pricing, read 30 Aug 2026; not yet compared against a real bill.

**Question.** What does cold storage of the raw gzipped archive cost, and does any layout breach the
kill line of **USD 60/month at month 12** (probes/README.md, row P4)?

**Answer in one line.** Not for the cold options: S3 Glacier Deep Archive in eu-west-1 with one tar
per cycle is USD 10–16/month at month 12 and USD 20–32/month at month 24 across the two measured
cycle sizes; every hot object store (R2, B2, Wasabi) breaches on storage alone between month 4 and
month 11. The traps are elsewhere: egress (restoring the whole archive out of AWS at month 12 is
USD 906–1,436, almost all of it the 0.09/GB internet transfer) and per-object requests (storing files
individually costs USD 55–88/month in PUTs alone, which is itself the kill line).

## Assumptions (all figures derive from these)

Two cycle sizes were measured on 30 Aug 2026 and both are priced side by side everywhere below as
**(a) / (b)**:

| Item | (a) morning manifest | (b) 15:28 UTC manifest | Source |
|---|---|---|---|
| Files per cycle | 11,099 | **17,861** (11,027 unique satellites; 6,834 of them listed with two files, i.e. two epochs) | P1; live `MANIFEST.txt` at 15:28 UTC |
| Bytes per file, gzip -6 | ~821,000 (one file measured; applied to both) | same | P1 |
| Bytes per cycle | 9,112,279,000 ≈ **9.11 GB** | 14,663,881,000 ≈ **14.66 GB** | computed |
| Growth (3 cycles/day, 30-day month) | 27.3 GB/day → **820 GB/month** | 44.0 GB/day → **1,320 GB/month** | computed |
| Stored at month 1 / 6 / 12 / 24 | 0.82 / 4.92 / **9.84** / **19.68 TB** | 1.32 / 7.92 / **15.84** / **31.67 TB** | computed |
| Storage unit (bundled) | one uncompressed tar of the cycle's gzipped files → **90 objects/month** | same | this probe |
| Storage unit (naive) | one object per file → 11,099 × 90 = **998,910 PUTs/month** | 17,861 × 90 = **1,607,490 PUTs/month** | this probe |
| Multipart parts per tar | 8 MB parts: **1,139**; 512 MB parts: **18** | 8 MB parts: **1,833**; 512 MB parts: **29** | computed |
| Daily derived-product build, one cycle/day read from the bucket | **273 GB/month** | **440 GB/month** | this probe |
| Restore whole archive at month 12 | 9.84 TB | 15.84 TB | this probe |

The true steady state is **unmeasured** and lies between (a) and (b): a second epoch per satellite
appears in (b) but not (a), and files may repeat across consecutive manifests. If they do, a
content-addressed layout (store each SHA-256 once, which D09/D10 already compute) stores each file
once and the real growth is nearer (a); if every cycle is fresh bytes, it is (b). P6 or the first
week of poller output settles it; until then the kill line is tested against (b).

Common assumptions:

| Item | Value |
|---|---|
| Uploader | non-AWS VPS in Europe (ingress from the internet) |
| Egress cases | restore one cycle to a non-AWS host; restore the whole archive at month 12 to a non-AWS host; the daily build reading one cycle/day from the bucket to the VPS |
| Units | decimal GB (10⁹ bytes) throughout. AWS bills in GiB, so AWS figures here are ~7% high (1 GB = 0.931 GiB). |
| EUR → USD | **1.1643** (ECB euro reference rate, 28 Aug 2026), `https://data-api.ecb.europa.eu/service/data/EXR/D.USD.EUR.SP00.A?lastNObservations=3&format=csvdata`, read 30 Aug 2026 |
| Month-N storage cost | price × bytes stored at the *end* of month N (upper bound; the mid-month average is ~4% lower at month 12) |
| Excluded | VAT (Hetzner and Scaleway quote ex-VAT), the VPS itself, Zenodo (free), OpenTimestamps (free) |

Sensitivity: every storage figure is linear in the 821,000-byte single-file sample. If the real
per-file mean is 10% higher, every storage number is 10% higher.

## Price sources

All read 30 Aug 2026 unless stated. "JSON" means the price feed the provider's own pricing page
loads client-side; the rendered HTML did not expose regional tables to the fetcher.

| # | Provider | Source | Notes |
|---|---|---|---|
| 1 | AWS S3 (Standard, Standard-IA, Glacier Flexible Retrieval, requests) | `https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/s3/USD/current/s3.json` (feed behind `https://aws.amazon.com/s3/pricing/`), publication date in feed 2026-08-18 | regions `EU (Ireland)` and `EU (Frankfurt)` |
| 2 | AWS S3 Glacier Deep Archive | `https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/s3glacierdeeparchive/USD/current/s3glacierdeeparchive.json`, feed date 2026-03-09 | same regions |
| 3 | AWS data transfer | `https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/datatransfer/USD/current/datatransfer.json`, feed date 2026-07-20 | same regions |
| 4 | AWS minimum durations / overhead | `https://docs.aws.amazon.com/AmazonS3/latest/userguide/storage-class-intro.html` | comparison table and footnotes |
| 5 | AWS multipart limits | `https://docs.aws.amazon.com/AmazonS3/latest/userguide/qfacts.html` | 5 MiB–5 GiB parts, 10,000 parts |
| 6 | Cloudflare R2 | `https://developers.cloudflare.com/r2/pricing/`, `https://developers.cloudflare.com/r2/objects/multipart-objects/`, `https://developers.cloudflare.com/r2/platform/limits/` | |
| 7 | Backblaze B2 | `https://www.backblaze.com/cloud-storage/pricing`, `https://www.backblaze.com/cloud-storage/transaction-pricing`, `https://www.backblaze.com/docs/cloud-storage-large-files` | |
| 8 | Wasabi | `https://wasabi.com/pricing`, `https://wasabi.com/pricing/pricing-faqs` | |
| 9 | Hetzner Storage Box | `https://www.hetzner.com/storage/storage-box/` and per-model pages fetched, but prices render client-side and were **not** captured. Numbers below are from `https://www.whtop.com/plans/hetzner.com/128270` (BX21), `/128271` (BX31), `/128272` (BX41), third-party snapshot dated 13 Feb 2026. | **Unverified against hetzner.com** |
| 10 | Scaleway Object Storage / Glacier | `https://www.scaleway.com/en/pricing/storage/` (Paris region), `https://raw.githubusercontent.com/scaleway/docs-content/main/pages/object-storage/faq.mdx`, `https://raw.githubusercontent.com/scaleway/docs-content/main/macros/object-storage/lifecycle-minimal-duration-message.mdx` | EUR, ex-VAT |

Not fetched: the AWS bulk price-list API (`pricing.us-east-1.amazonaws.com/offers/...`) returned
`NoSuchKey`/`InvalidRequest` for every path tried from this client; the pricing-page JSON feeds above
were used instead and cross-check each other (Glacier Flexible storage is identical in `s3.json` and
the legacy `glacier.json`).

## Unit prices as read

USD unless marked. "IE" = EU (Ireland), "FR" = EU (Frankfurt).

| Provider / class | Storage per GB-month | Write requests | Read / retrieval | Egress to internet | Minimum / overhead |
|---|---|---|---|---|---|
| S3 Glacier Deep Archive, IE | **0.00099** | PUT / POST / CompleteMultipart / Lifecycle-in 0.055 per 1,000; UploadPart / InitiateMultipart 0.005 per 1,000 | Bulk 0.003 per GB + 0.025 per 1,000 requests; Standard 0.020 per GB + 0.11 per 1,000; GET 0.0004 per 1,000 | first 100 GB/month free (all AWS, aggregated); then 0.09 per GB to 10 TB, 0.085 next 40 TB, 0.07 next 100 TB, 0.05 above | 180-day minimum; 40 KB per object (32 KB at DA rate + 8 KB at S3 Standard rate 0.023); early-delete billed at 0.00099 per GB-month remaining |
| S3 Glacier Deep Archive, FR | 0.0018 | 0.060 / 0.0054 per 1,000 | Bulk 0.005 per GB + 0.030 per 1,000; Standard 0.024 per GB + 0.12 per 1,000 | as above | as above |
| S3 Glacier Flexible Retrieval, IE | 0.0036 | PUT / COPY / POST / Lifecycle-in 0.033 per 1,000; CopyPart 0.005 per 1,000 (plain UploadPart to this class is not listed separately in the feed — priced here at 0.005 per 1,000 by analogy with Deep Archive and CopyPart; worst case 0.033) | Bulk **free** per GB and per request; Standard 0.010 per GB + 0.055 per 1,000; Expedited 0.030 per GB + 0.011 per request | as above | 90-day minimum; 40 KB per object as above |
| S3 Standard-IA, IE | 0.0125 | PUT / COPY / POST / LIST 0.010 per 1,000; Lifecycle-in 0.010 per 1,000 | 0.010 per GB retrieval; GET 0.001 per 1,000 | as above | 30-day minimum; 128 KB minimum billable object |
| S3 Standard, IE (staging for restores) | 0.023 first 50 TB | 0.005 per 1,000 | GET 0.0004 per 1,000 | as above | none |
| Cloudflare R2 Standard | 0.015 | Class A (PutObject, UploadPart, CompleteMultipartUpload, CreateMultipartUpload, ListObjects…) 4.50 per million; first 1 million/month free | Class B (GetObject, HeadObject) 0.36 per million; first 10 million/month free | **free** | none; 10 GB-month free |
| Cloudflare R2 Infrequent Access | 0.010 | Class A 9.00 per million, no free tier | Class B 0.90 per million; **data retrieval 0.01 per GB** on every read | free | 30-day minimum |
| Backblaze B2 | 6.95 per TB (0.00695) | Class A (PutObject, UploadPart, CompleteMultipartUpload…) **free** | Class B (GetObject) and Class C (List) **free**; Class D (event notifications) 0.004 per 10,000 after 2,500/day | free up to **3× average monthly storage**; then 0.01 per GB; unlimited free to Cloudflare, Fastly, bunny.net, CacheFly, CoreWeave, Equinix Metal, Vultr, phoenixNAP | none; no minimum file size; first 10 GB free |
| Wasabi (NA and EMEA) | 7.99 per TB (0.0078 per GB as Wasabi rounds it; 0.00799 used here) | free | free | free while monthly egress ≤ active storage volume; Wasabi "reserve[s] the right to limit or suspend" if regularly exceeded | **1 TB minimum monthly charge**; **90-day** timed-delete charge; API requests free but shown on invoice |
| Hetzner Storage Box (unverified, see §Price sources) | BX21 5 TB €10.90 (USD 12.69); BX31 10 TB €20.80 (USD 24.22); BX41 20 TB €40.60 (USD 47.27); ex-VAT; BX41 is the largest model listed | none (SFTP/SCP/rsync/Samba/WebDAV/Borg/Restic/Rclone; no S3 API) | none | **unlimited** ("traffic use is free of cost") | 10 concurrent connections per box; snapshots 20/30/40; setup fee amount not captured |
| Scaleway Glacier (Paris, Amsterdam only) | €0.00254 (USD 0.00296) | included | restore €0.009 per GB (USD 0.0105); "a few minutes to 24 hours" for restore to start | 75 GB/month free, then €0.01 per GB (USD 0.0116) | 1,000 parts max per object, 5 MB–5 GB per part; transition rules created after 1 Apr 2026 require 90 days in Standard before Glacier (30 days before One Zone); whether a direct `PUT` with `x-amz-storage-class: GLACIER` bypasses this is **not verified** |
| Scaleway Standard One Zone / Multi-AZ | €0.00803 (USD 0.0093) / €0.01606 (USD 0.0187) | included | — | as above | — |

## Comparison

Every money cell is **(a) / (b)**. Storage at month N uses the bytes stored at the end of month N.
"Bundled" = 90 tars per month at 8 MB parts unless stated; "unbundled" = one object per file.

### Storage only, USD per month

| Option | Month 1 | Month 6 | Month 12 | Month 24 | First month storage alone exceeds USD 60 |
|---|---|---|---|---|---|
| S3 Deep Archive, IE | 0.81 / 1.31 | 4.87 / 7.84 | **9.74 / 15.68** | **19.49 / 31.36** | 74 / 46 |
| S3 Deep Archive, FR | 1.48 / 2.38 | 8.86 / 14.25 | 17.71 / 28.51 | 35.43 / 57.01 | 41 / 26 |
| S3 Glacier Flexible, IE | 2.95 / 4.75 | 17.71 / 28.51 | 35.43 / 57.01 | 70.86 / 114.03 | 21 / 13 |
| S3 Standard-IA 30 days → Deep Archive IE (two-tier) | 10.25 / 16.50 | 14.31 / 23.03 | **19.18 / 30.87** | **28.93 / 46.55** | 63 / 35 |
| S3 Standard-IA alone, IE | 10.25 / 16.50 | 61.51 / 98.98 | 123.02 / 197.96 | 246.03 / 395.92 | 6 / 4 |
| Cloudflare R2 Standard | 12.30 / 19.80 | 73.81 / 118.78 | 147.62 / 237.55 | 295.24 / 475.11 | 5 / 4 |
| Cloudflare R2 Infrequent Access | 8.20 / 13.20 | 49.21 / 79.18 | 98.41 / 158.37 | 196.83 / 316.74 | 8 / 5 |
| Backblaze B2 | 5.70 / 9.17 | 34.20 / 55.03 | 68.40 / 110.07 | 136.79 / 220.13 | 11 / 7 |
| Wasabi | 7.99 (1 TB min) / 10.54 | 39.32 / 63.27 | 78.63 / 126.54 | 157.26 / 253.08 | 10 / 6 |
| Hetzner Storage Box (unverified) | 12.69 BX21 / 12.69 BX21 | 12.69 BX21 (4.92 of 5 TB) / 24.22 BX31 (7.92 of 10 TB) | **24.22 BX31** (9.84 of 10 TB) / **47.27 BX41** (15.84 of 20 TB) | **47.27 BX41** (19.68 of 20 TB) / **71.49** BX41 + BX31 (31.67 TB; no single box is large enough) | never at (a) / 19 at (b) |
| Scaleway Glacier | 2.43 / 3.90 | 14.55 / 23.42 | **29.10 / 46.84** | **58.21** / 93.67 | 25 / 16 |

Hetzner boxes are outgrown at months 6.1 / 12.2 / 24.4 under (a) and 3.8 / 7.6 / 15.2 under (b);
several of the cells above leave under 2% headroom and Hetzner does not state whether its "TB" is
decimal — assume you upgrade one month early. Under (b) the 20 TB BX41 is full by month 16 and there
is no larger box: months 16–18 fit in BX41 + BX21 (USD 59.96), month 19 onward needs BX41 + BX31.

### Requests, retention penalties, ingress, egress

| Option | Write cost, bundled (90 tars/month) | Write cost, unbundled (one object per file) | Retention / per-object penalty | Restore one cycle (9.11 / 14.66 GB) to non-AWS host | Restore whole archive at month 12 (9.84 / 15.84 TB) to non-AWS host | Ingress | Daily build reading one cycle/day from bucket to VPS (273 / 440 GB per month) | Egress to CDN / build host free? |
|---|---|---|---|---|---|---|---|---|
| S3 Deep Archive, IE | 8 MB parts: **0.52 / 0.83**; 512 MB parts: **0.01 / 0.02** | 998,910 × 0.055/1,000 = **54.94** / 1,607,490 × 0.055/1,000 = **88.41** per month, every month | 180-day minimum is irrelevant (nothing is deleted). Unbundled adds 40 KB per object: at month 12, 12.0M / 19.3M objects → **2.59 / 4.16 per month and growing** | Bulk: 0.03 / 0.04 retrieval + egress inside the 100 GB free tier ≈ **0.03 / 0.04** (0.85 / 1.36 if the free tier is already used); Standard: 0.18 / 0.29 + egress; 12–48 h wait | Bulk retrieval 29.52 / 47.51 + 1,080 requests 0.03 + egress 876.71 / 1,388.34 → **≈ 906 / 1,436**; with Standard retrieval ≈ 1,074 / 1,705. Restored copies also occupy S3 Standard staging for the restore window (0.021 per GB-month: ≈ 48 / 78 for 7 days). Unbundled adds 12.0M / 19.3M restore requests: bulk **+300 / +482**, standard **+1,319 / +2,122** | free | Not practical from DA (12–48 h per restore). If forced: bulk 0.82 / 1.32 + egress (273 − 100) × 0.09 = 15.60 / (440 − 100) × 0.09 = 30.59 → **16.4 / 31.9 per month** | No. 0.09 per GB to any non-AWS host (CloudFront origin fetches are free but the build host is not CloudFront) |
| S3 Deep Archive, FR | ≈ 0.56 / 0.90 (8 MB) | 59.93 / 96.45 | as IE at 0.0018 | Bulk 0.05 / 0.07 + egress | Bulk 49.21 / 79.18 + egress 876.71 / 1,388.34 ≈ **926 / 1,468** | free | as IE | No |
| S3 Glacier Flexible, IE | 0.52 / 0.83 (parts at 0.005) to 3.38 / 5.44 (parts at 0.033) | 998,910 × 0.033/1,000 = **32.96** / **53.05** | 90-day minimum irrelevant; 40 KB per object as above | Bulk retrieval **free**, 5–12 h; egress inside free tier ≈ **0** | Bulk free + egress 876.71 / 1,388.34 ≈ **877 / 1,388**; with Standard retrieval 98.41 / 158.37 more | free | Bulk free + egress 15.60 / 30.59 → **15.6 / 30.6 per month**, 5–12 h latency per read | No |
| S3 Standard-IA 30 d → Deep Archive, IE | ≈ 1.03 / 1.65 (parts at 0.010) + 90 transitions × 0.055/1,000 ≈ **1.04 / 1.66** | PUT 9.99 / 16.07 + **lifecycle transitions 54.94 / 88.41** = 64.93 / 104.48 | IA 30-day minimum matches the 30-day window; DA overhead as above | From IA (last 30 days): retrieval 0.09 / 0.15 + egress ≈ **0.1–0.9 / 0.2–1.5**; older cycles as DA row | ≈ 92% in DA, 8% in IA: bulk 27.06 / 43.55 + IA retrieval 8.20 / 13.20 + egress 876.71 / 1,388.34 ≈ **912 / 1,445** | free | Reads the newest cycle from IA: retrieval 2.73 / 4.40 + egress 15.60 / 30.59 = **18.3 / 35.0 per month**, millisecond access | No |
| Cloudflare R2 Standard | 102,510 / 164,970 Class A inside the 1M/month free tier → **0** (0.46 / 0.74 if the free tier is consumed elsewhere) | 998,910 Class A ≈ at the free-tier edge → **0 to 4.50**; 1,607,490 → 607,490 over the free tier → **2.73** (7.23 with no free tier) | none | **0** | **0** (Class B negligible) | free | **0** | Yes — egress free to anywhere |
| Cloudflare R2 Infrequent Access | 102,510 / 164,970 × 9.00/M = **0.92 / 1.48** | **8.99 / 14.47** | 30-day minimum irrelevant; retrieval 0.01 per GB on every read | 0.09 / 0.15 | 98.41 / 158.37 retrieval, egress free → **98 / 158** | free | **2.73 / 4.40 per month** | Yes, but every read pays 0.01 per GB |
| Backblaze B2 | **0** | **0** | none | **0** (within 3× allowance) | **0** — 9.84 / 15.84 TB is within the 29.5 / 47.5 TB per month allowance at month 12 | free | **0** | Yes; unlimited to listed CDN partners, 3× storage to anyone else, then 0.01 per GB |
| Wasabi | 0 | 0 | 1 TB minimum (bites only in month 1 under (a)); 90-day timed-delete charge irrelevant | 0 | 0 in money, but a whole-archive restore equals **100% of stored volume** in that month — at the policy limit | free | 0 | Yes within the ≤ stored-volume policy |
| Hetzner Storage Box (unverified) | none | none (but 1–1.6M files/month on SFTP is an inode and rsync-time problem, not a money one) | fixed box; upgrade steps at 5 / 10 / 20 TB, nothing above 20 TB | 0 | 0 (unlimited traffic; 10 concurrent connections cap throughput) | free | 0 | Yes |
| Scaleway Glacier | included; **8 MB parts are impossible** (1,139 / 1,833 > 1,000-part cap) — use ≥ 10 / ≥ 15 MB parts | included | 1,000-part cap; 90-day-in-Standard rule for lifecycle transitions after 1 Apr 2026 (direct PUT to Glacier unverified). If a 90-day One Zone window is required: + 3 months × 0.0093 per GB ≈ **+23.0 / +37.0 per month** | restore €0.08 / €0.13 + egress inside 75 GB free ≈ **0.10 / 0.15**; up to 24 h wait | restore 9,841 × €0.009 = €88.57 / €142.53 + egress (stored − 75) × €0.01 = €97.66 / €157.62 → **≈ 217 / 349** | free | egress (273 − 75) × €0.01 = 2.31 / 4.25 + restore 2.86 / 4.61 → **5.2 / 8.9 per month**, with up to 24 h latency per read | No; 75 GB/month free then 0.0116 per GB |

## Reading

### Under the USD 60/month line?

Routine bill = storage + bundled writes (8 MB parts) + the daily build's egress/retrieval. Two cases
for the build: "local" (the VPS builds from the copy it just pulled, so nothing leaves the bucket)
and "from bucket". Cells are **(a) / (b)**; **bold** = over the line.

| Option (bundled) | Month 12, build local | Month 12, build from bucket | Month 24, build local | Month 24, build from bucket |
|---|---|---|---|---|
| S3 Deep Archive, IE | 10.3 / 16.5 | 26.7 / 48.4 (and impractical: 12–48 h) | 20.0 / 32.2 | 36.4 / **64.1** |
| S3 Deep Archive, FR | 18.3 / 29.4 | 34.7 / **61.3** | 36.0 / 57.9 | 52.4 / **89.8** |
| S3 Glacier Flexible, IE | 36.0 / 57.8 | 51.6 / **88.4** | **71.4 / 114.9** | **87.0 / 145.5** |
| S3 Standard-IA 30 d → Deep Archive, IE | 20.2 / 32.5 | 38.5 / **67.5** | 30.0 / 48.2 | 48.3 / **83.2** |
| Cloudflare R2 Standard | **147.6 / 237.6** | **147.6 / 237.6** | **295.2 / 475.1** | **295.2 / 475.1** |
| Cloudflare R2 IA | **99.3 / 159.9** | **102.1 / 164.3** | **197.8 / 318.2** | **200.5 / 322.6** |
| Backblaze B2 | **68.4 / 110.1** | **68.4 / 110.1** | **136.8 / 220.1** | **136.8 / 220.1** |
| Wasabi | **78.6 / 126.5** | **78.6 / 126.5** | **157.3 / 253.1** | **157.3 / 253.1** |
| Hetzner BX31 / BX41 (unverified) | 24.2 / 47.3 | 24.2 / 47.3 | 47.3 / **71.5** | 47.3 / **71.5** |
| Scaleway Glacier | 29.1 / 46.8 | 34.3 / 55.7 | 58.2 / **93.7** | **63.4 / 102.5** |

Against the kill line (month 12, build local):

- **(a) 820 GB/month:** under the line — Deep Archive (either region), Glacier Flexible, the IA→DA
  two-tier, Hetzner BX31, Scaleway Glacier. Also under at month 24: Deep Archive IE and FR, the
  two-tier, Hetzner BX41, Scaleway Glacier (by USD 1.80).
- **(b) 1,320 GB/month:** under the line — Deep Archive IE (16.5), Deep Archive FR (29.4), the
  two-tier (32.5), Hetzner BX41 (47.3, unverified), Scaleway Glacier (46.8), Glacier Flexible (57.8,
  no margin). Still under at month 24: only Deep Archive IE (32.2), the two-tier (48.2) and Deep
  Archive FR (57.9). Hetzner runs out of box sizes at month 16; Scaleway Glacier and Glacier Flexible
  cross the line at months 16 and 13.
- Every hot object store (R2, B2, Wasabi) breaches on storage alone between month 4 and month 11
  at either growth rate, regardless of free egress.

Unbundled storage (one object per file) breaches on AWS from month 1 on requests alone (Deep Archive
54.94 / 88.41 per month, Glacier Flexible 32.96 / 53.05, plus the two-tier's lifecycle transitions
at the same 54.94 / 88.41), and turns a whole-archive Deep Archive restore into 12–19M restore
requests (+300 / +482 bulk, +1,319 / +2,122 standard). On R2/B2/Wasabi/Hetzner it is free or nearly
so, but it is still the wrong shape for a Merkle-rooted cycle whose identity is the manifest hash
(D10). One tar per cycle it is.

### Cheapest defensible default

**S3 Glacier Deep Archive, eu-west-1 (Ireland), one uncompressed tar per cycle, multipart at 512 MB
parts, build products from the VPS's local copy.** USD 10.3 / 16.5 per month at month 12,
USD 20.0 / 32.2 at month 24, USD 0.01–0.02/month in requests, no ingress charge. Ireland is 45%
cheaper than Frankfurt for this class (0.00099 vs 0.0018) and identical on egress. Tag each tar with
the cycle id and Merkle root in object metadata; never read from it in the daily path. It is the only
option that stays under the line at month 24 under (b) with room to spare.

Second copy (D03 wants two pollers; a single-vendor archive is a single point of failure): under (a)
the only two-copy layout under USD 60 at month 24 is Deep Archive IE + Deep Archive FR (≈ 55 at
month 24, same vendor); Deep Archive + Hetzner BX41 is ≈ 67 at month 24 and ≈ 35 at month 12;
Deep Archive + Scaleway Glacier ≈ 78 at month 24. Under (b) no two-copy layout survives month 24
(IE + FR ≈ 88; IE + Hetzner ≈ 64 already at month 12), and only IE + FR (≈ 46) survives month 12.
If a second, different-vendor copy is required, the kill line needs a decision entry raising it, or
the second copy holds only the daily Merkle-root manifests and a sampled subset (which is what the
Wayback captures under D07 already are).

### The single biggest trap in each option

- **S3 Deep Archive:** getting the data *out*. Restoring the month-12 archive to a non-AWS host is
  ≈ USD 906 / 1,436, of which USD 877 / 1,388 is the 0.09/GB internet egress; storage for the same
  month is USD 9.74 / 15.68. A restore into an EC2 instance in the same region avoids the egress line
  entirely, so the recovery plan must be "restore in-region, verify Merkle roots there, ship out only
  what is needed". Also: first byte in 12–48 hours, so nothing user-facing may depend on it.
- **S3 Glacier Flexible Retrieval:** it costs 3.6× Deep Archive for a retrieval time (5–12 h bulk) the
  project cannot use in a daily path anyway; storage alone crosses USD 60 at month 21 / 13. Same
  egress trap as Deep Archive.
- **S3 Standard-IA hot window + Deep Archive:** the IA layer is a fixed ≈ USD 10.25 / 16.50 per month
  for data the VPS already has locally; and any build that reads from IA pays 0.01/GB retrieval *and*
  0.09/GB egress (≈ USD 18 / 35 per month at one cycle per day). The lifecycle transitions are cheap
  only because the objects are bundled (90 vs 1.0–1.6M per month).
- **Cloudflare R2:** no cold tier. Infrequent Access is 0.010/GB-month — ten times Deep Archive —
  and charges 0.01/GB on every read; storage alone breaches at month 8 / 5 (Standard at month 5 / 4).
  Free egress is worth nothing if the archive is not there.
- **Backblaze B2:** 0.00695/GB-month is seven times Deep Archive; breaches at month 11 / 7. Its
  free egress is real (3× stored volume per month, unlimited to Cloudflare), which makes it the best
  *warm* store if the growth rate ever drops or the kill line rises — but not at 0.8–1.3 TB/month.
- **Wasabi:** the egress policy, not the price. Free egress is conditioned on monthly egress ≤ stored
  volume, so a whole-archive restore consumes the entire month's allowance and a second one invites
  suspension. Plus a 1 TB minimum bill and 90-day timed-delete charges; breaches at month 10 / 6.
- **Hetzner Storage Box:** it is a single NAS share in one datacentre with a 10-connection cap, not
  object storage: no S3 API, no published durability figure, and no per-object immutability. The
  price is the best in the table but is **unverified** here (hetzner.com renders prices client-side;
  the numbers are a third-party snapshot dated 13 Feb 2026). Sizes step at 5/10/20 TB with nothing
  above 20 TB, so under (b) it stops being a single box at month 16.
- **Scaleway Glacier:** three things. The 1,000-part cap means 8 MB parts fail on a 9–15 GB tar; the
  post-April-2026 rule that lifecycle transitions need 90 days in Standard first may force a
  ≈ USD 23 / 37 per month hot window if direct-to-Glacier PUTs are not allowed (not verified); and
  Glacier is Paris/Amsterdam only, with the Paris copy in one underground site. Whole-archive restore
  ≈ USD 217 / 349, a quarter of AWS, because egress is €0.01/GB.

### What this probe did not do

- No real bill. The next step is a 30-day trial: push real cycle tars to Deep Archive IE with 512 MB
  parts, keep the AWS bill, and write the actual figure back here with its date.
- Did not measure the steady-state cycle size or file repetition across manifests (which decides
  whether (a) or (b) is the real growth, and whether a content-addressed layout halves it).
- Hetzner prices and Scaleway direct-to-Glacier PUT behaviour are unverified (see above).
- Did not price Zenodo (free, 50 GB per record) for derived products, or any cost of the second
  poller's VPS; those are not "the archive".
- Did not price a Deep Archive restore into EC2 (in-region transfer is free by AWS's rule, but the
  instance and its EBS volume for 10–16 TB were not priced).
