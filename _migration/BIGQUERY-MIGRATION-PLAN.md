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

  **Do not confuse the two "free" things** (this caused a real question on 2026-08-31, and
  getting it wrong would mean opening a second GCP account for no reason):

  | | GCP Free Trial | BigQuery free usage tier |
  |---|---|---|
  | What | $300 promotional credit | 10 GiB storage + 1 TiB queries **per month** |
  | Duration | 90 days, then gone | **Permanent** — part of standard BigQuery pricing |

  The 90-day clock is on the credit, not on access. The free usage tier is not a promotion
  and does not expire; it is simply how BigQuery bills. At 630 KiB of data and a few MB
  scanned per `dbt build`, this estate sits at ~0.006% of the storage allowance. There is no
  second trial to chase — that was the whole reason BigQuery beat another Snowflake trial.

  **The one thing that actually needs doing:** convert the billing account to pay-as-you-go
  before the trial ends (~2026-11-29 for a trial started 2026-08-31). If the trial lapses
  without converting, resources are suspended and then deleted after a grace period — that
  is the account lacking a payment relationship, not the free tier ending. Upgrading costs
  $0 on its own. Set a **$1 budget alert** at the same time: if it ever fires, a query is
  wrong, not the plan.

  **Set the query-usage quota as part of that same conversion — added 2026-09-01.** A
  10 GiB/day cap on *Query usage per day* (BigQuery API, in *Quotas & System Limits*) bounds
  worst-case scanning to ~310 GiB/month, under the permanent 1 TiB/month free allowance. It
  matters because a `jobUser` credential can query `bigquery-public-data`, which is petabytes,
  billed to this project — the quota makes that arithmetically impossible rather than merely
  unlikely.

  It could not be set during Phase 1: **quota edits require an upgraded billing account**, and
  the Free Trial cannot make them. That is acceptable only because the trial *cannot be
  charged* — credits deplete and resources stop, no bill is issued. So the protection today is
  the trial itself, and converting to pay-as-you-go is precisely what removes it. Conversion
  and quota are therefore one action, not two: upgrading without the quota is the only
  configuration in this plan where a mistake costs real money.
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
stay inside the free tier — at ~3,400 rows that is four orders of magnitude of headroom.

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
| `analytics.prod_snapshots.*` | `<proj>.prod_snapshots.*` |
| `analytics.mesh_dev.*` | `<proj>.mesh_dev.*` |

**`prod_snapshots` was added to this table on 2026-08-31** — the original mapping omitted it
because the schema had been missed entirely. That made this an 8-dataset migration, not 7. It
would have surfaced as a confusing failure at Phase 5, when the production job first tried to
snapshot into a dataset nobody had created.

Two things survive untouched: the deliberate `raw` vs `raw_mesh` separation persists as
distinct dataset prefixes (so the `customers`/`orders` collision avoidance still holds),
and the `schema: snapshots` → `dbt_learning_snapshots` suffixing is dbt's own
`generate_schema_name`, not a Snowflake behaviour, so it carries over unchanged.

## Phase 1 — Provision GCP (~45 min) — USER

1. Create GCP project; enable the BigQuery API.
2. Service account with **BigQuery Data Editor** + **BigQuery Job User** at project level.
3. JSON key → `~/.dbt/keys/bq_dbt_sa.json` (same dir as the Snowflake keys, already
   outside the public repo).
4. Create **all 8 datasets** from the table above — `raw_jaffle_shop`, `raw_stripe`,
   `raw_mesh_jaffle_shop`, `dbt_learning`, `dbt_learning_snapshots`, `prod`, `prod_snapshots`,
   `mesh_dev`. **Set location once and consistently — `EU`.** Datasets in different regions
   cannot be joined, and location cannot be changed after creation.
5. `pip install google-cloud-bigquery`.

Note: no `gcloud` or `bq` CLI on this machine (checked). Python 3.13.2 + pip work, so the
client library is the lighter path than installing the full Cloud SDK.

**Genuine simplification:** the PKCS#8-vs-PKCS#1 dual-envelope problem disappears. BigQuery
takes one JSON keyfile, identical locally and in dbt Cloud.

Verify with `python _migration/verify_phase1.py` before starting Phase 2. It checks the three
things that fail *later* rather than at creation time: dataset location (a wrong region only
breaks on the first cross-region join), default table expiration (bites 60 days in), and the
IAM roles (a 403 on the first `dbt run`).

### Steps 2–3: blocked by org policy, then resolved — 2026-09-01

The GCP organization enforces `iam.disableServiceAccountKeyCreation` (Google's "Secure by
Default"), which blocked service-account key creation. **Resolved by overriding the constraint
at project scope only** — the key now exists at `~/.dbt/keys/bq_dbt_sa.json` with Data Editor +
Job User, and the policy stays enforced everywhere else in the org, permanently.

Three wrong turns, each worth remembering because each cost a round trip:

1. **Disabling the constraint org-wide** was the console's own suggestion and the first thing
   considered. Rejected: it removes the protection everywhere, forever, to unblock one project.
   Org policies support **per-resource overrides**, so the correct scope is the project.
2. **`iam.managed.disableServiceAccountKeyCreation` is a different policy.** The `.managed.`
   prefix marks Google's newer managed-constraints family; it is a separate object with its own
   enforcement state. Overriding it changes nothing about the legacy constraint. The error
   message's *"Enforced Organization Policies IDs"* line names the one actually blocking the
   call — read it rather than pattern-matching on the name.
3. **The OAuth consent screen's "Internal" user type failed** with `Error 403: org_internal`,
   for the Owner account too. Internal admits only members of the org's domain; the Owner here
   is a personal Gmail *granted* Owner on the project, not a domain member. An org existing is
   not the same as your account belonging to it.

The keyless OAuth path built before the override landed is **kept, not reverted** — `bq_creds`
prefers the keyfile and falls back to OAuth, so it costs nothing to retain and is the standing
answer if key creation is ever blocked again (or for a machine where dropping a key is not
wanted). Phase 5 (dbt Cloud) is no longer gated on this: it needs a key, and a key now exists.

**Do not re-enforce the override now that the key exists.** Re-enforcing blocks future key
*rotation* while doing nothing about the key already on disk — the appearance of compliance in
exchange for the ability to replace a key suspected of being compromised.

The keyless path (three files, all committed):

- `bq_creds.py` — one loader every script authenticates through. Prefers
  `~/.dbt/keys/bq_dbt_sa.json` if it ever exists, falls back to `~/.dbt/keys/bq_oauth.json`.
  Nothing else in the migration had to change to accommodate the policy.
- `bq_oauth_setup.py` — one-time browser consent, writes the refresh token. Requires an
  OAuth 2.0 **Desktop app** client, which the policy does *not* govern.
- `verify_phase1.py` — authenticates through `bq_creds`, so it works under either credential.

If that fallback is ever needed, two things to get right in the console:

- Consent screen user type. **Internal** has no token expiry but admits only accounts in the
  org's domain — it fails with `org_internal` for a Gmail merely granted Owner. **External**
  works with any account but, left in "Testing", issues refresh tokens that expire after
  **7 days**; publishing to remove that expiry needs Google verification, because
  `.../auth/bigquery` is a sensitive scope. Neither option is free.
- Only the `bigquery` scope is requested, not `cloud-platform`.

**Why the keyfile is the better credential here, now that both were built:** the OAuth token is
the user's own identity, which holds Owner on the project — *broader* than Data Editor + Job
User — and it either expires in 7 days or cannot be consented to at all. The service-account key
is least privilege, does not expire, and works in dbt Cloud. Its one real weakness is the
reason the org policy exists: a leaked key works forever, from anywhere, with no second factor.
Mitigations in place: it lives in `~/.dbt/keys/` outside all three repos, `.json` credential
patterns were added to every repo's `.gitignore` (they previously covered only Snowflake's
`.p8`/`.pem`), and the SA holds no `serviceAccountKeyAdmin`, so it cannot mint further keys.

## Phase 2 — Load raw data (~45 min)

Python loader over the **9 raw CSVs** in `snowflake-export-20260829/` (11 files total, minus
the two snapshot exports), using `SOURCE-TYPES.md` for explicit schemas.

- **Lowercase every column header** (landmine 1).
- **Explicit types, not autodetect.** Autodetect gets `payment.amount` right (INTEGER,
  cents) but may read `order_date` as STRING.
- **Skip both snapshot CSVs** — `snapshot_orders_snapshot.csv` and
  `prodsnapshot_orders_snapshot.csv` are Phase 6, and loading them here would give dbt a
  snapshot table it thinks it built.
- Row counts to assert against are in `../PARITY-BASELINE-20260831.csv` (`n_rows`). Loading
  without checking counts is how a truncated CSV becomes a silent data loss.

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
the varchar timestamps parsed back (including the `9999-12-31` sentinel).

**Do the same for `prodsnapshot_orders_snapshot.csv` → `<proj>.prod_snapshots.orders_snapshot`**
(added 2026-08-31). Lower stakes: all 104 of its rows are open, so it carries no closed history
— but the production job will append to whatever it finds, and finding nothing means restarting
production history from scratch. Because the export
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

### Row-level derived export — added 2026-08-31, second reference side

The aggregate-only baseline was a time-pressure choice, **not a technical limit**, and the user
caught that: the derived models are materialized (or queryable) in Snowflake exactly like the raw
tables, so nothing stopped them being exported row-for-row too. The account was still reachable,
so they now are — `export_derived.py` → `snowflake-export-derived-20260831/`, **40 objects /
11,685 rows**, plus a `MANIFEST.csv` carrying per-file row counts and sha256.

Why it matters — the aggregates have two real blind spots:

- **Compensating errors.** Two rows swapping a value leaves `n_rows`, `n_nonnull`, `n_distinct`
  and `sum` all identical. A row-level diff catches it; the fingerprint cannot.
- **TEXT and TIMESTAMP columns are thinly covered.** They get `min..max` plus `n_distinct` and no
  `sum`, so a corruption in the middle of the range that preserves distinctness is invisible.

It also changes a mismatch from a *detection* into a *diagnosis*: with only aggregates you learn
that a column differs, not what the right value was. With the rows on disk you can see which side
is wrong.

Two deliberate choices in the exporter:

- **Rows are sorted in Python on the rendered tuple, not by a SQL `order by`.** A SQL sort over a
  text column is collation-dependent, so the two warehouses can legitimately order matching rows
  differently and a line-by-line diff would misalign on correct data.
- Headers lowercased and values rendered by `sf_query.render()` — the same renderer that produced
  the raw CSVs, so all three artifacts are formatted consistently.

Verified on capture: all 40 row counts agree with `n_rows` in `PARITY-BASELINE-20260831.csv`, and
the 12 dev/prod object pairs are **byte-identical by sha256** — which re-confirms the zero-drift
finding by a wholly different method than the aggregate sweep.

### Typed Parquet export — added 2026-08-31, the authoritative reference side

The user's next objection was also correct: **CSV carries no types.** Every value in those files
is a string, so `12.50` and `12.5` are different bytes for the same `NUMBER(38,2)` and a Phase 7
diff has to re-guess every column's type before it can compare — which is the very problem the
parity work exists to remove. So the same 40 objects were re-exported as Parquet:
`export_derived_parquet.py` → `snowflake-export-derived-20260831/parquet/`, **576 KiB**.

Note the storage direction, which is the opposite of the intuition: Parquet is **less than half
the size of the CSVs** (576 KiB vs 1.3 MiB) *and* typed. Columnar layout plus dictionary encoding
plus snappy beats text comfortably. Type fidelity is not a storage cost here — it is a saving.
(Excel would have been strictly worse than CSV, not better: xlsx stores numbers as IEEE-754
doubles, so a `NUMBER(38,2)` loses exactness past ~15 significant digits.)

**The landmine, found by verifying rather than assuming.** The first Parquet run was wrong in a
way that looked completely fine. `snowflake-connector-python` defaults to
`arrow_number_to_decimal=False`, which converts any fixed-point `NUMBER` with non-zero scale to
`float64` on the way into Arrow. It also narrows integers to whatever the *observed values* fit —
`customer_id NUMBER(38,0)` came back as `int8`, because no id exceeded 127. So the naive export
stored exact decimals as floating point and encoded this snapshot's value range as if it were the
column's type:

| Snowflake declared | Driver inferred | Asserted instead |
|---|---|---|
| `NUMBER(38,2)` / `(38,6)` / `(38,4)` | `double` | `decimal128(p, s)` |
| `NUMBER(38,0)` | `int8` | `decimal128(38, 0)` |
| `NUMBER(18,0)` / `(4,0)` / `(2,0)` | `int8` / `int16` | `int64` |
| `TIMESTAMP_NTZ` | `timestamp[ns]` | `timestamp[us]` |

The fix is two-part and the order matters: set `arrow_number_to_decimal=True` **before the fetch**
(casting afterwards cannot repair it — by then `0.1` is already the nearest binary double), then
`cast()` the table to a schema derived from `information_schema.columns` rather than from the
driver's inference. The cast is left `safe=True` on purpose, so a mapping that would lose data
raises instead of quietly producing a plausible-looking reference file.

**The transferable lesson: the file format is not the guarantee.** Parquet is perfectly capable of
storing a float where a decimal belonged. What makes types portable is asserting the schema and
verifying the round-trip — the format only preserves whatever you actually handed it.

Two judgment calls, both recorded rather than hidden:

- `scale == 0` maps to `int64` when precision ≤ 18 and to `decimal128(p, 0)` above it, so nothing
  can overflow. That means `NUMBER(38,0)` keys land as `decimal128`, while BigQuery's own models
  will produce `INT64` — so Phase 7 must compare type *families* here, exactly as
  `PARITY-BASELINE.md` already requires.
- `TIMESTAMP_*` maps to microseconds to match BigQuery's `DATETIME`/`TIMESTAMP` resolution rather
  than Snowflake's nanosecond default. Lossless for this data, and proven so: the safe cast would
  have raised on any sub-microsecond value.

Verified: **every value in all 40 Parquet files renders identically to its CSV counterpart** —
so the two exports corroborate each other, and any later disagreement means corruption in one.

**Both formats are kept deliberately.** Parquet is authoritative for Phase 7 comparison; the CSVs
stay because they are greppable, human-readable and diffable in a git history, which a binary
columnar file is not.

New local dependencies: `pyarrow` (25.0.1) and `pandas` (3.0.5) — the connector gates
`fetch_arrow_all()` behind its pandas extra, so both are required, not just pyarrow.

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

- [x] Data exported — `snowflake-export-20260829/`, 11 tables / 3,355 rows (verified row-for-row 2026-08-31), commit `cbd2bcb`
- [x] Production 06:00 job confirmed healthy 2026-08-29; type verified by measurement 2026-08-31
- [x] `analytics.prod_snapshots.orders_snapshot` exported 2026-08-31 — **missed by the original
      export**, found by an information-schema sweep. 104 rows, all open, no unique history.
- [x] Phase 7 reference side captured — `PARITY-BASELINE-20260831.csv`, commit `176ca79`
- [x] Phase 7 reference side **strengthened to row level 2026-08-31** —
      `snowflake-export-derived-20260831/`, 40 objects / 11,685 rows, counts cross-checked against
      the baseline and dev/prod confirmed byte-identical. Closes the aggregate blind spots
      (compensating errors, thin TEXT/TIMESTAMP coverage).
- [x] Full estate sweep: 9 non-system schemas across 3 databases, all accounted for.
      `SNOWFLAKE_LEARNING_DB` is empty; `ANALYTICS.PUBLIC` is stale and deliberately skipped.
- [x] **dbt Cloud 06:00 job unscheduled 2026-08-31** (user, dbt Cloud UI) — before the trial
      lapsed, so it never fails nightly on a dead connection. Must be recreated in Phase 5.
- [x] **Keyless auth path built 2026-09-01** — `bq_creds.py`, `bq_oauth_setup.py`, and
      `verify_phase1.py` patched to authenticate through the loader. Written because
      `iam.disableServiceAccountKeyCreation` blocks Phase 1 step 3 and lifting the constraint
      org-wide is a worse trade than routing around it.
- [x] `.json` credential patterns added to all three repos' `.gitignore` 2026-08-31 — they
      covered only Snowflake's `.p8`/`.pem`, so a BigQuery keyfile was uncovered. Verified with
      decoy filenames and `git check-ignore -v`.
- [x] Phase 1 steps 2–3 — **service-account key created 2026-09-01** after overriding
      `iam.disableServiceAccountKeyCreation` at *project* scope. Org stays protected elsewhere.
      Roles: Data Editor + Job User only.
- [x] Phase 1 step 5 — `google-cloud-bigquery` 3.44.0 + `google-auth-oauthlib` installed.
- [ ] Phase 1 remainder (user): enable **BigQuery API**, create the **8 datasets in `EU`** with
      default table expiration cleared, $1 budget alert. Then `python _migration/verify_phase1.py`.
      Query-usage quota is **not settable on the Free Trial** — moved to the pay-as-you-go
      conversion, see "Why BigQuery over the alternatives".
- [ ] Phases 2–6, 8

### Revised order

1 → 2 → 3 → 4 → 6 → 5 → 8. Phase 7 folds in wherever convenient after 3, since it no longer
needs a live Snowflake. Phase 5 (dbt Cloud) moved after 6 because rewiring the scheduler is
pointless until the snapshot it builds on is restored — and it is now also the only phase that
needs a service-account key, so deferring it defers the org-policy decision too.
