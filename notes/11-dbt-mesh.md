# 11 — dbt Mesh

**Status:** complete — with one part unexercised, see *The blocker* below.

## What this course covers

Splitting one monolithic project into multiple governed projects — model contracts, versions,
access modifiers, cross-project `ref()`.

Done across two repos rather than two folders, which is the point: `core_platform`
(`mesh/platform`, repo `dbt-mesh-platform`) produces, `jaffle_finance` (`mesh/finance`, repo
`dbt-mesh-finance`) consumes. Both share the `mesh` profile and the `mesh_dev` dataset.

## The blocker: cross-project `ref()` needs dbt Cloud Enterprise

`{{ ref('core_platform', 'fct_orders') }}` resolving *across two separate dbt projects* is a
dbt Cloud **Enterprise** feature. It works by a `dependencies.yml` in the consumer naming the
upstream project, and dbt Cloud then serving the producer's manifest to the consumer at parse
time. There is no local equivalent — the producer's manifest simply isn't reachable, so Core
and Fusion both fail to resolve the ref.

What is reachable locally is the **package** route: put `core_platform` in the consumer's
`packages.yml` as a git package and ref it the same way.

```yaml
packages:
  - git: https://github.com/shyngysapsemetov-source/dbt-mesh-platform.git
    revision: main
```

**The syntax is identical.** `ref('<project_or_package>', '<model>')` is the same two-argument
form either way; only resolution differs — a package is vendored into the consumer's own DAG,
a cross-project ref stays out of it. That distinction is the whole substance of Mesh, and it is
exactly what the package route costs you:

| | cross-project ref (Cloud Enterprise) | package (Core / Fusion) |
|---|---|---|
| producer models in consumer's DAG | no | **yes, all of them** |
| `dbt build` in consumer rebuilds producer | no | **yes**, unless selected out |
| producer owns its own schedule & schema | yes | no |
| `access:` enforced at the boundary | yes | to be verified — see *Open questions* |
| lineage across the boundary | yes | yes |

So the package route reproduces the *authoring* experience and loses the *deployment*
separation. Worth saying plainly in an interview rather than implying the boundary was real.

## Key concepts

### The three mechanisms, and what each one actually buys

Mesh is not one feature. It is three, and they are independently useful even inside one project.

1. **Contracts** — `config: contract: enforced: true`. dbt builds the model with an explicit
   DDL (`create table … (col type, …)`) instead of `create table as select`, so a column that
   disappears or changes type fails the *producer's* build rather than the consumer's query.
   Requires `data_type` on **every** column in the yml; a missing one hard-fails.
2. **Versions** — two physical relations can coexist, so a breaking change ships without a
   flag-day migration for consumers.
3. **Groups + access** — `groups.yml` names an owner; `access:` says who may `ref()` the model.
   `public` / `protected` (default) / `private`.

Contracts are the load-bearing one. Versions without a contract are two tables that might both
be wrong; access without a contract just restricts who gets to be surprised.

### Contracts require a declared type on every column

```yaml
models:
  - name: fct_orders
    config:
      contract:
        enforced: true
    columns:
      - name: order_id
        data_type: string
        constraints:
          - type: not_null
```

Enforced on `int_orders`, `fct_orders`, `fct_order_items`, `dim_product_supplies` — the four
tables. **Not** on staging: BigQuery views cannot carry `NUMERIC(p, s)` at all, so a contract
declaring `numeric(12, 2)` on a view fails every time. See `notes/03` for the measurement.

A `not_null` **constraint** is not a `not_null` **test**. The constraint is in the DDL, so the
build fails and nothing lands; the test runs after the table is already written and readable.
For a model another project consumes, constraint is the right tool. `unique` has no constraint
equivalent on BigQuery — `primary_key` is accepted but is planner metadata only, not enforced —
so the grain stays a test, placed on `int_orders` where the joins that could break it happen.

### Versions

```yaml
    latest_version: 2
    versions:
      - v: 1
      - v: 2
        columns:
          - name: order_amount
            data_type: numeric(12, 2)
          - include: all
            exclude: [order_total]
```

- Top-level `columns:` is the shared definition; each `versions:` entry **patches** it.
- `include: all` / `exclude: [...]` is how a version subtracts from the shared list.
- One `.sql` file per version: `fct_orders_v1.sql`, `fct_orders_v2.sql`. The bare
  `fct_orders.sql` is deleted — a versioned model has no unversioned file.
- Consumers pin with `{{ ref('fct_orders', v=1) }}`; an unpinned `ref` follows `latest_version`.
- `dbt list` shows them as `core_platform.marts.fct_orders.v1` / `.v2`.

### Deprecating a version

`deprecation_date:` on a version (or on the model) makes dbt warn at parse time in every
project that refs it. It does not block the build. That is the mechanism that makes versions a
migration path rather than permanent duplication.

## Commands used

```bash
dbt list --resource-type model          # confirms versions resolve as fct_orders.v1 / .v2
dbt compile                             # 11 models, 28 tests, 39/39
dbt build --select fct_orders           # builds both versions
dbt show --inline "select … from \`…mesh_dev.INFORMATION_SCHEMA.COLUMNS\`"
```

## Gotchas hit

### Versioning an existing model is a destructive table → view migration

Before: `mesh_dev.fct_orders` was a `BASE TABLE`. After: `fct_orders_v1` and `fct_orders_v2`
are tables and `fct_orders` is a **VIEW**. BigQuery cannot convert a table to a view in place,
so dbt drops the table and creates the view. On a real table that is a data-loss event for
anything not reproducible from source, and anything reading the bare name got a relation of a
different *kind* with no warning. The lesson is that adding `versions:` to a live model is a
migration to schedule, not a yml edit.

### **Fusion synthesizes a latest-version pointer view; dbt Core does not**

Measured on 2.0.0-preview.218, `mesh_dev` after a full build:

| object | kind |
|---|---|
| `fct_orders_v1` | BASE TABLE |
| `fct_orders_v2` | BASE TABLE |
| `fct_orders` | **VIEW** |

dbt Core has no third object. In Core the latest version is *aliased* to the bare name, so you
get `fct_orders_v1` (table) and `fct_orders` (table, which **is** v2) — two objects, and no
`fct_orders_v2` at all. **Exam answers assume the Core layout.** Anything that enumerates
relations — a parity check, a `INFORMATION_SCHEMA` audit, an external BI tool's table list —
sees a different set of objects on each engine.

### The pointer view drops NUMERIC precision — but `ref()` never reads the pointer

`fct_orders_v2` stores `NUMERIC(12, 2)` and `NUMERIC(6, 4)`, exactly as the contract declares.
The `fct_orders` view over it reports bare `NUMERIC` — precision and scale gone. Same BigQuery
limitation that forced contracts off the staging layer (`notes/03`).

**Who this reaches, verified by reading the compiled SQL rather than assuming:** nobody inside
dbt. An *unpinned* `{{ ref('core_platform', 'fct_orders') }}` from `jaffle_finance` compiles to

```sql
select * from `dbt-learning-507213`.`mesh_dev`.`fct_orders_v2`
```

— the suffixed **table**. `ref()` resolves to the version's own relation whether or not you pass
`v=`; the pointer view is not in the resolution path at all. So a dbt consumer always gets the
contracted types, and pinning changes *which version* you read, never how precisely it is typed.

The loss lands only on consumers that reach the bare name outside dbt — a BI tool, a hand-written
query, an `INFORMATION_SCHEMA` audit. Which is exactly who the pointer exists for, so the group
that benefits from the stable name is the same group that silently loses the declared scale.

⚠️ `mesh/platform` commit `eef44c2`'s message states this the wrong way round — it claims
`ref('fct_orders')` gets the loose type. It doesn't. The commit message was written before the
compiled SQL was read; this section is the correct version.

### `latest_version: 2` renamed a column, which is a parity divergence by design

v2 renames `order_total` → `order_amount` and casts `location_opened_at` to `DATE`. The
Snowflake→BigQuery parity checker therefore reports `fct_orders` as divergent on `ORDER_TOTAL`.
That is course content doing what course content does, **not** a migration regression — recorded
in `_migration/PARITY-BASELINE.md` so a future run isn't misread.

### Access across a package boundary: `protected` is not a boundary, `private` is

Measured 2026-09-23 with `jaffle_finance` consuming `core_platform` as a git package. Probed with
a real model file, not `dbt show --inline`, because an inline node is not a project model and
might not be subject to the same checks — it wasn't, but that had to be established rather than
assumed.

| producer model's `access` | ref from the consuming project | result |
|---|---|---|
| `public` (`fct_orders`) | `ref('core_platform', 'fct_orders')` | allowed |
| `protected`, the default (`int_orders`, all six `stg_*`) | `ref('core_platform', 'int_orders')` | **allowed** |
| `private` to group `product` | same ref | **`AccessDenied (dbt1066)`** |

So **installing a project as a package makes it the same project for access purposes.**
`protected` means "not reachable by a *cross-project* ref", and a package ref is not that. Which
means `access: public` on `fct_orders` is **decorative in this setup** — finance could read
`int_orders`, or any staging view, with nothing to stop it. The governance half of Mesh is the
half the package route does not reproduce, and this is where that shows up concretely.

`private` is the one modifier that still bites, and it bites harder than expected: it is scoped
to the **group**, not the project, so marking `int_orders` private to `product` broke
`fct_orders_v1`, `fct_orders_v2` and `fct_order_items` — **platform's own models** — because they
aren't in that group either. Four `dbt1066` errors from one line of yml. `private` is for "only
the models in this group may build on this", not for "keep other projects out".

The practical consequence: if you want a real boundary without Cloud Enterprise, `access:` won't
give it to you. What does is not shipping the models — a package that exposes only its marts, or
declaring the producer's outputs as `sources:` in the consumer instead.

### Generic test arguments must be nested under `arguments:` on Fusion

The `relationships` tests added to the staging FKs need:

```yaml
- relationships:
    arguments:
      to: ref('stg_jaffle_shop__orders')
      field: order_id
```

The flat form every `dbt_utils` example online uses hard-fails with
`DbtYamlValidationError (dbt1159)`. Core still accepts the legacy form — **the exam will show
the flat version.** Same session: `tests:` is renamed `data_tests:`.

## Open questions

- ~~**Does `access: protected` block a ref from a package?**~~ **Answered 2026-09-23** — see
  *Access across a package boundary* below.
- `fct_order_items` and `dim_product_supplies` still have no `group`, and the `product` group is
  declared and attached to nothing. Which marts belong to which domain is a modelling call, not
  a config one — left open deliberately.
- `deprecation_date` was read about, not exercised. Nothing here has a real consumer to warn yet.
