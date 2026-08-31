# Snowflake → BigQuery migration plan

Written 2026-08-29. Covers all three projects: `dbt_fundamentals` (`jaffle_shop`),
`mesh/platform` (`core_platform`), `mesh/finance` (`jaffle_finance`).

## Why migrate at all

The Snowflake trial expires **~2026-09-01** (revised down from ~09-04 on 2026-08-31). Four courses remain on the dbt Certified
Developer path (8 Advanced Testing, 9 Advanced Deployment, 10 Exposures, 11 dbt Mesh)
plus the exam.

Migrating *before* course 9 rather than after, because:

1. **The deadline dissolves.** On a forever-free platform, courses 8/10/11 and the exam
   stop being a race. Right now the trial is the only thing forcing a sprint.
2. **Course 9 is Advanced Deployment** — it *is* the wiring of environments, scheduling
   and CI. Done on a dying trial, that setup gets built twice: once as a discarded
   exercise, once for real. Done after migrating, the exercise *is* the real
   infrastructure.
3. **A fresh Snowflake trial on another email costs almost the same as migrating** —
   reload all data, redo key-pair auth in both envelopes, re-point both profiles, rebuild
   the dbt Cloud connection — and lands back at this same decision around 2026-10-04.

Verified prerequisite: **dbt Fusion 2.0.0-preview.212 supports BigQuery.** Probed the
local binary directly — supported adapters are `snowflake, bigquery, databricks,
redshift, duckdb, salesforce, clickhouse`. Only Postgres is excluded (experimental, behind
`DBT_ALLOW_EXPERIMENTAL_ADAPTERS=true`). So there is no adapter risk.

## Why BigQuery over the alternatives

- **BigQuery** — chosen. Best match for the roles being targeted; forever-free tier
  (10 GiB storage, 1 TiB queries/month). Cost is the namespace rework below.
- **Databricks Free Edition** — least rework (Unity Catalog's `catalog.schema.table` maps
  1:1), but market signal skews enterprise/data-engineering rather than consumer analytics.
- **DuckDB** — cannot be the main target: **dbt Cloud has no DuckDB connection type**, so
  course 9 would be impossible. Reserved for a future public portfolio repo, where
  "a reviewer can clone it and it just runs" is the whole point.

## Two landmines found up front

Both verified 2026-08-29. Each would cost an afternoon if hit mid-migration.

### 1. Column case will break every staging model

Models select lowercase (`select id, first_name, last_name` in
`stg_jaffle_shop_customers.sql`). Snowflake resolves unquoted identifiers
case-insensitively; **BigQuery is case-sensitive**. The exported CSVs carry UPPERCASE
headers (`ID`, `FIRST_NAME`) because that is how Snowflake stored them.

Loading them as-is → `Name id not found inside source` on every staging model.
**Fix: lowercase all column headers at load time.** Then every existing lowercase model
works unchanged.

### 2. Do NOT use the BigQuery sandbox

The sandbox needs no credit card but **expires every table after 60 days**. It would
silently delete models and the snapshot mid-certification. Use a real billing account and
stay inside the free tier — at 3,241 rows that is four orders of magnitude of headroom.

## Phase 0 — Namespace model (decided)

Snowflake is `database.schema.table`; BigQuery is `project.dataset.table`. Same depth, so
a 1:1 three-project mirror looks tempting. **It does not work:** GCP project IDs are
globally unique, so `raw` / `analytics` are long taken and every `database:` value changes
anyway — the zero-edit benefit evaporates and cross-project IAM is left over for nothing.

Decision: **one GCP project, database+schema collapsed into dataset names.**

| Snowflake | BigQuery |
|---|---|
| `raw.jaffle_shop.*` | `<proj>.raw_jaffle_shop.*` |
| `raw.stripe.payment` | `<proj>.raw_stripe.payment` |
| `raw_mesh.jaffle_shop.*` | `<proj>.raw_mesh_jaffle_shop.*` |
| `analytics.dbt_learning.*` | `<proj>.dbt_learning.*` |
| `analytics.dbt_learning_snapshots.*` | `<proj>.dbt_learning_snapshots.*` |
| `analytics.prod.*` | `<proj>.prod.*` |
| `analytics.mesh_dev.*` | `<proj>.mesh_dev.*` |

Two things survive untouched: the deliberate `raw` vs `raw_mesh` separation persists as
distinct dataset prefixes (so the `customers`/`orders` collision avoidance still holds),
and the `schema: snapshots` → `dbt_learning_snapshots` suffixing is dbt's own
`generate_schema_name`, not a Snowflake behaviour, so it carries over unchanged.

## Phase 1 — Provision GCP (~45 min) — USER

1. Create GCP project; enable the BigQuery API.
2. Service account with **BigQuery Data Editor** + **BigQuery Job User** at project level.
3. JSON key → `~/.dbt/keys/bq_dbt_sa.json` (same dir as the Snowflake keys, already
   outside the public repo).
4. Create the 7 datasets above. **Set location once and consistently — `EU`.** Datasets in
   different regions cannot be joined, and location cannot be changed after creation.
5. `pip install google-cloud-bigquery`.

Note: no `gcloud` or `bq` CLI on this machine (checked). Python 3.13.2 + pip work, so the
client library is the lighter path than installing the full Cloud SDK.

**Genuine simplification:** the PKCS#8-vs-PKCS#1 dual-envelope problem disappears. BigQuery
takes one JSON keyfile, identical locally and in dbt Cloud.

## Phase 2 — Load raw data (~45 min)

Python loader over the 10 CSVs in `snowflake-export-20260829/`, using `SOURCE-TYPES.md`
for explicit schemas.

- **Lowercase every column header** (landmine 1).
- **Explicit types, not autodetect.** Autodetect gets `payment.amount` right (INTEGER,
  cents) but may read `order_date` as STRING.
- **Skip the snapshot** — that is Phase 6.

## Phase 3 — Profiles + dialect fixes (~2 h)

**Replace** the Snowflake targets — the original reason to keep them was Phase 7's live
comparison, and that reference is now a committed CSV instead. Keeping a dead target only
invites `--target dev` typos that fail confusingly.

```yaml
default:
  target: bq
  outputs:
    bq:
      type: bigquery
      method: service-account
      keyfile: C:/Users/ashyngys/.dbt/keys/bq_dbt_sa.json
      project: <gcp-project-id>
      dataset: dbt_learning
      location: EU
      threads: 16
```

Edit `database:`/`schema:` in `_src_jaffle_shop.yml`, `_src_stripe.yml` (fundamentals) and
`models/staging/__sources.yml` (platform). Then the four dialect fixes:

| File | Change |
|---|---|
| `models/intermediate/int_order_payments.sql:11` | `'1900-01-01'::timestamp` → `cast('1900-01-01' as timestamp)` |
| `models/intermediate/int_order_payments.sql:37` | `cast(… as number(38,2))` → **re-derive, see below** |
| `snapshots/snapshots.yml:11` | `to_date('9999-12-31')` → `date '9999-12-31'` |
| `macros/load_payment_batch.sql` | `'…'::date` ×2 → `date '…'` |

`current_timestamp()` is portable — no change. The `dbt_utils` / `audit_helper` /
`dbt_project_evaluator` hits in a dialect grep are package-internal integration-test
profiles; those packages already ship BigQuery variants.

**The `number(38,2)` cast is a judgment call, not a translation.** It exists because
`on_schema_change: sync_all_columns` attempted a scale change and Snowflake refused with
error `040052`. BigQuery's `NUMERIC` is fixed precision 38 / scale 9 and its
schema-evolution rules differ, so the original reason may not apply — but removing the cast
changes the model's output type, and `_int.yml` records that `on_schema_change` behaviour is
what broke `fct_orders` once. Decide deliberately and verify; do not swap mechanically.

Gate: `dbt build` green in `dbt_fundamentals` against `--target bq`.

## Phase 4 — Mesh projects (~30 min)

Add a `bq` target to the second profile and **rename it** — `profile: snowflake` in both
mesh `dbt_project.yml` files becomes a lie after migration. Platform's sources move to
`raw_mesh_jaffle_shop`.

Finance needs nothing beyond the profile. Its three models are deliberately broken with
bare `select * from fct_orders` and no `packages.yml`, for course 11 to fix. **Leave that
alone — it is the exercise.**

## Phase 5 — Rewire dbt Cloud (~1 h)

New BigQuery connection (same JSON key). Recreate both environments — Development →
`dbt_learning`, Production → `prod`, branch `main` — and the `0 6 * * *` `dbt build` job
with docs-on-run. Run Production manually once before trusting the schedule.

## Phase 6 — Restore snapshot history (~45 min, delicate)

`dbt snapshot` cannot produce this — it would create fresh history with one valid-from row.
Load `snapshot_orders_snapshot.csv` **directly** into
`<proj>.dbt_learning_snapshots.orders_snapshot`, with dbt's meta columns typed correctly and
the varchar timestamps parsed back (including the `9999-12-31` sentinel). Because the export
preserved `dbt_scd_id`, later `dbt snapshot` runs append rather than restart.

**Known imperfection:** `dbt_scd_id` is an md5 over key + `updated_at`, and timestamp→string
casting differs between Snowflake and BigQuery. dbt may therefore compute different hashes
for unchanged rows and add one extra version row per order on the first BigQuery run.
Cross-warehouse snapshot continuity is imperfect in principle. The achievable goal is
preserving the record of the 4 rows closed on 2026-08-20; a cosmetic extra version is the
price. Expect it rather than debugging it.

## Phase 7 — Parity check — REFERENCE SIDE ALREADY CAPTURED, no deadline

**Rewritten 2026-08-31, when the trial window turned out to be 1 day, not 6.** The original
plan — keep Snowflake targets alive and compare the two warehouses side by side — was
unreachable: GCP was still unprovisioned and Phases 1–3 are ~3.5 h before a single BigQuery
model exists to compare against.

So the Snowflake side was **recorded as a committed artifact** instead:
`PARITY-BASELINE-20260831.csv`, 49 objects / 306 column rows of deliberately portable
aggregates (`count(*)`, `count(col)`, `count(distinct col)`, `sum()` for numerics, `min..max`
otherwise) plus full precision/scale types. Method in `make_fingerprint.py`, rationale and
comparison rules in `PARITY-BASELINE.md`.

Phase 7 is now **"diff BigQuery against the file"** and can happen calmly next week. The
deadline became an artifact. Snowflake targets no longer need to survive in `profiles.yml`.

Two results already banked from it, while Snowflake was alive to ask:

- **Dev and prod have zero drift** — all 12 objects match on every column, type, row count and
  aggregate. Nothing to reconcile during migration.
- **The `NUMBER(38,6)` production worry was a false alarm.**
  `PROD.INT_ORDER_PAYMENTS.TOTAL_ORDER_AMOUNT` is `NUMBER(38,2)`, same as dev. Measured, not
  inferred from "the job runs fine".

When comparing, expect `full_type` to differ everywhere (`NUMBER(38,0)` → `INT64`,
`TIMESTAMP_NTZ` → `DATETIME`) and compare type *families*; treat text `min`/`max` mismatches as
collation questions. `n_rows`, `n_nonnull`, `n_distinct` and numeric `sum` must match exactly.

## Phase 8 — Decommission (~15 min)

No longer gated on Phase 7 — Snowflake is going away on ~2026-09-01 whatever happens, and the
parity reference now lives in a CSV rather than in the account. Drop the Snowflake targets from
`profiles.yml` as part of Phase 3, then: retire the `.p8`/`.pem` keys, update
`profiles.yml.example`, rewrite the Snowflake setup sections of the dbt memory store, and
**remove `snowflake` from the dbt-coach trigger list** — `~/.claude/skills/dbt-coach/SKILL.md`
(description + opening line) and the `TRIGGER` regex in `~/.claude/hooks/dbt_coach_gate.py`.
`bigquery` was added to both on 2026-08-31; the Snowflake half stays until the estate is
actually off it. Let the trial lapse on its own.

Keep `~/.dbt/sf_query.py` (the ad-hoc query helper written 2026-08-31) as the template for a
BigQuery equivalent — it is the thing that made this baseline possible, and the pattern
generalises.

**Do not write the real GCP project ID into this file.** `dbt-learning` is a public repo —
keep `<proj>`. The Snowflake account identifier was nearly committed here once already.

## Effort

~6–8 hours across two days. Then courses 9, 8, 10, 11 and the exam run on infrastructure
that still exists in November.

## Status

**Nothing is now blocked by the Snowflake trial.** Everything that expired with it has been
captured; the remaining work runs on a schedule of your choosing.

- [x] Data exported — `snowflake-export-20260829/`, 10 tables / 3,241 rows, commit `cbd2bcb`
- [x] Production 06:00 job confirmed healthy 2026-08-29; type verified by measurement 2026-08-31
- [x] `analytics.prod_snapshots.orders_snapshot` exported 2026-08-31 — **missed by the original
      export**, found by an information-schema sweep. 104 rows, all open, no unique history.
- [x] Phase 7 reference side captured — `PARITY-BASELINE-20260831.csv`, commit `176ca79`
- [x] Full estate sweep: 9 non-system schemas across 3 databases, all accounted for.
      `SNOWFLAKE_LEARNING_DB` is empty; `ANALYTICS.PUBLIC` is stale and deliberately skipped.
- [ ] **Pause the dbt Cloud 06:00 job before the trial lapses** (user, dbt Cloud UI). Otherwise
      it fails nightly on a dead connection and burns run minutes and failure emails.
- [ ] Phase 1 — GCP provisioning (user)
- [ ] Phases 2–6, 8

### Revised order

1 → 2 → 3 → 4 → 6 → 5 → 8. Phase 7 folds in wherever convenient after 3, since it no longer
needs a live Snowflake. Phase 5 (dbt Cloud) moved after 6 because rewiring the scheduler is
pointless until the snapshot it builds on is restored.
