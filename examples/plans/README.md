# Authored Backchain adapter fixtures

`braid` and `confetti` pair a request with a fixed Backchain-schema plan and a
separate explicit execution-binding file. They are reviewable protocol fixtures:
the test suite submits them to the selected Backchain checkout's real
`--package-only` validator. They demonstrate structural import and execution
binding, not native semantic planning, dependency discovery, or convergence by a
model.

Each plan's `goal` is exactly the bytes of its paired `../<recipe>.request.txt`.
Do not rewrite either request before submitting its plan: the script rejects a
plan whose goal differs from the frozen request. `inputs[].from` declares direct
supplier step IDs. `goal_needs` names the required terminal facts: Braid has its
published note, while Confetti has both independent terminal notes.

Run these commands from the repository root. Replace the Backchain checkout path
with the source checkout that the planning packet selected.

```sh
DEMO=$(mktemp -d)
mkdir "$DEMO/workspace"

./weave init \
  --prompt-file examples/braid.request.txt \
  --backchain-root /absolute/path/to/backchain \
  --repo "$DEMO/workspace" \
  --run-dir "$DEMO/run" > "$DEMO/planning.json"

ACTION_ID="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["action_id"])' "$DEMO/planning.json")"

./weave accept-plan \
  --run-dir "$DEMO/run" \
  --action "$ACTION_ID" \
  --plan examples/plans/braid.plan.json \
  --bindings examples/plans/braid.bindings.json

./weave run --run-dir "$DEMO/run"
./weave next --run-dir "$DEMO/run"
```

Braid is command-only, so `run` reaches `status=complete` after its two joins.
The final `next` is a cold-recovery check; it does not rerun accepted commands.

To use Confetti, substitute `confetti` in all three fixture paths. Its seed is a
command, then the script returns each terminal prompt packet. Have the host carry
out that packet in its returned workspace (`$DEMO/workspace` for these commands),
write the returned `result_file`, and
invoke its exact `complete` callback. After one terminal receipt, the other leaf
remains required; the run reports `complete` only after both receipts are accepted.

The focused adapter coverage is:

```sh
python3 -m unittest tests/test_prompt_examples.py -v
```
