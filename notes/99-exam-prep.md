# Exam prep — Analytics Engineering Certification

<!-- Numbered 99 deliberately: this is the exam at the end of the path, not a course
     within it, so it stays last however many courses get added ahead of it. -->

**Status:** not started

## Exam shape

<!-- Fill in from the official exam study guide once you're at this stage. -->

Topic areas (per dbt Labs' study guide):

1. Developing dbt models
2. Debugging data modeling errors
3. Monitoring data pipelines
4. Implementing dbt tests
5. Deploying dbt jobs
6. Using dbt commands
7. Understanding state
8. Leveraging the dbt Cloud IDE

## Weak spots

<!-- The single most valuable section in this file. Add a line every time a practice
     question catches you out, then revisit only this list before the exam. -->

## Command flags worth memorising

```bash
dbt run --select state:modified+ --defer --state ./prod-artifacts   # slim CI
dbt build --exclude tag:heavy
dbt run --select tag:nightly
dbt ls --resource-type model --select marts
dbt retry                                                          # rerun from failure point
```

## Selector syntax cheat sheet

| Selector | Meaning |
|---|---|
| `model_a` | just that model |
| `model_a+` | model and all descendants |
| `+model_a` | model and all ancestors |
| `@model_a` | ancestors, the model, descendants, and descendants' ancestors |
| `model_a+2` | model plus 2 levels downstream |
| `tag:finance` | everything tagged `finance` |
| `path:models/marts` | everything under a path |
| `state:modified` | changed vs a stored manifest |
| `source_status:fresher` | sources newer than the last run |

## Practice log

| Date | What | Score / result |
|---|---|---|
| | | |
