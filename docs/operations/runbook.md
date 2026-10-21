# Runbook

Every command below exists in this repository or in the Azure CLI with the `ml` extension. The
workspace is `mlw-careintel-prod-swc` in `rg-careintel-prod-swc`; pass
`-w mlw-careintel-prod-swc -g rg-careintel-prod-swc` to every `az ml` command, omitted below for
readability.

## A drift issue was opened

`drift-check.yml` opened an issue titled *Cohort drift* with the share of drifted features, the
list of features and the retraining run.

1. Read the drifted features. A broad shift in demographics or adherence is a population change; a
   shift concentrated in one family of columns, such as every `measurement_*`, usually means a
   coding or extract change upstream, which is a data problem before it is a model problem.
2. Reproduce it locally against the current extract:
   ```
   make drift CURRENT=path/to/current.parquet VERSION=<asset version>
   ```
3. Follow the retraining run:
   ```
   az ml job show -n <retraining run> --query status
   ```
   Its `register` step ends in one of three ways, recorded as run parameters: `champion` when
   there was none, `challenger` when it beat the champion on cost avoided per thousand contacts,
   or `rejected`.
4. A challenger is promoted only through `deploy-prod.yml`, which a named reviewer approves. Read
   the comparison and the subgroup audit of both versions before approving. A rejection closes the
   issue with the reason, and the champion keeps serving.

## A pipeline failed

The alert `alert-careintel-pipeline-failed` fires on any failed run in the workspace.

1. Find the failed step:
   ```
   az ml job list --parent-job-name <run> -o table
   ```
2. Read its logs:
   ```
   az ml job download -n <step> --all --download-path logs
   ```
3. Known causes, all measured on this workspace:

| Symptom in the logs | Cause | Fix |
|---|---|---|
| `SchemaDriftError` in `prep` | The extract broke the contract in `data/schema.json` | Fix the extract; change the schema only together with a new model version |
| `Failed to pull Docker image` | The step did not run as `id-careaml` | Every step runs as the pipeline identity and the sweep trials run on the cluster that carries it; check `AML_IDENTITY_CLIENT_ID` |
| `KeyBasedAuthenticationNotPermitted` while mounting data | The workspace cached storage credentials | `az ml workspace update -n mlw-careintel-prod-swc --system-datastores-auth-mode accesskey`, then the same command with `identity`. Never run `az ml workspace sync-keys` on this workspace |
| `Failed to create table` in a batch job | The cluster identity lacks table or queue access | `id-careaml` needs Storage Table and Queue Data Contributor, declared in `infra/modules/workspace.bicep` |
| A step stays queued | Quota for the VM family | `az ml compute list-usage`, then wait or lower the concurrency |

4. Rerun once the cause is fixed:
   ```
   make pipeline
   ```

## Rollback

**Online traffic.** A bad deployment leaves traffic in seconds:
```
az ml online-endpoint update -n ep-readmission-risk --traffic "blue=100 green=0"
```
Swap the colours to match the deployment that served before. `deploy-prod.yml` does this by
itself when its smoke check fails.

**Registry.** The champion is the version tagged `stage=champion`. To restore the previous one:
```
az ml model update -n readmission-risk --version <bad> --set tags.stage=retired
az ml model update -n readmission-risk --version <previous> --set tags.stage=champion
```
The next training run is then gated against the restored champion.

**Weekly batch.** Redeploy batch scoring on a known version:
```
python -m ops.endpoints --batch --model-version <previous>
```

## Cost hygiene

The online endpoint bills its instance around the clock and is the largest fixed cost of this
workload. Delete it between demonstrations; `deploy-prod.yml` recreates it.
```
az ml online-endpoint delete -n ep-readmission-risk --yes
```
The compute cluster scales to zero by itself five minutes after its last job.
