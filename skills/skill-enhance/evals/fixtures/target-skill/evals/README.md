# Sample Target Skill Evals

Fixture-only eval directory used by `skill-enhance` tests.

## Files

- `train-queries.json` checks basic trigger and near-miss behavior for the fixture skill.
- `validation-queries.json` checks held-out trigger and near-miss behavior.
- `evals.json` contains minimal output-quality cases for the fixture skill.

## Expected Use

From the `skill-enhance` package root, this fixture should be runnable with:

```bash
scripts/run-evals.sh --skill evals/fixtures/target-skill --workspace /tmp/skill-enhance-fixture-evals --baseline snapshot
```
