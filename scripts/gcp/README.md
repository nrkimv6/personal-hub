# GCP Provisioning CLI

Idempotent Python CLI that wraps `gcloud`/`bq`/`gsutil` to provision personal-hub GCP resources.

## Quick start (dry-run)

```bash
# From repo root — no GCP credentials needed, nothing is created
python -m scripts.gcp.provision --resource all
```

## Apply (real provisioning — needs GCP credentials + billing account)

```bash
python -m scripts.gcp.provision --resource bigquery --apply
python -m scripts.gcp.provision --resource cloud-run --apply
python -m scripts.gcp.provision --resource all --apply
```

## Cost-guard gated resources

Cloud Build and Artifact Registry are **off by default**:

```bash
ENABLE_ARTIFACT_REGISTRY=true python -m scripts.gcp.provision --resource cloud-build --apply
ENABLE_CLOUD_BUILD=true python -m scripts.gcp.provision --resource cloud-build --apply
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GCP_PROJECT_ID` | `personal-hub-project` | GCP project id |
| `GCP_REGION` | `asia-northeast3` | Deployment region |
| `GCP_BQ_DATASET` | `personal_hub_events` | BigQuery dataset name |
| `GCP_AR_REPO` | `personal-hub-repo` | Artifact Registry repo name |
| `GCP_CLOUD_RUN_SERVICE` | `personal-hub` | Cloud Run service name |
| `ENABLE_CLOUD_BUILD` | `false` | Enable Cloud Build trigger provisioning |
| `ENABLE_ARTIFACT_REGISTRY` | `false` | Enable Artifact Registry provisioning |

## Resource coverage

| Resource | Module | Cost-guard |
|----------|--------|------------|
| BigQuery dataset + `personal_hub_events` table | `bigquery.py` | — (free tier) |
| Cloud Run service | `cloud_run.py` | — (min-instances=0) |
| Artifact Registry repo | `cloud_build.py` | `ENABLE_ARTIFACT_REGISTRY=true` |
| Cloud Build trigger | `cloud_build.py` | `ENABLE_CLOUD_BUILD=true` |

## Looker Studio

Looker Studio dashboard creation and publish are **manual steps** (CLI/API support is limited).
This CLI provisions the BigQuery dataset/table as a data source only.
Dashboard setup: https://lookerstudio.google.com/ → connect `personal_hub_events`.

## Deploy owner sequence

1. Ensure GCP project, billing, and APIs are enabled.
2. `python -m scripts.gcp.provision --resource bigquery --apply`
3. `python -m scripts.gcp.provision --resource cloud-run --apply`
4. (Optional) Enable and provision Cloud Build + AR with env-var overrides.
5. Live verification (todo-16): `gcloud run services describe personal-hub --region asia-northeast3 --format='value(status.url)'`

## Free-tier guards (hardcoded in `_config.py`)

- BigQuery: 10 GB storage, 1 TB/month query, 730-day partition expiration, `require_partition_filter=true`
- Cloud Run: `min-instances=0` (no idle charge)
- Artifact Registry: 0.5 GB cap, cleanup policy 30-day retention + keep 10
- Cloud Build: 120 build-min/day cap (gated off by default)
