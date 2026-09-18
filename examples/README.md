# Recipe lab

Each recipe uses local files only. Start with a fresh workspace/run pair; preserve
that run for recovery. Commands below run from the repository root.

```sh
DEMO=$(mktemp -d)
mkdir "$DEMO/workspace"
./weave init --workflow examples/braid.workflow.json --repo "$DEMO/workspace" --run-dir "$DEMO/run"
./weave run --run-dir "$DEMO/run"
```

| Recipe | What to inspect | Behavioral test |
| --- | --- | --- |
| Relay (`serial`) | numbers.csv → report.json → verification.txt | `tests/test_engine.py` |
| Diamond | Join receives both suppliers' receipts | `tests/test_engine.py` |
| Braid | extract/classify → consolidate → compose/check → publish (local file only) | `tests/test_graph_shapes.py` |
| Confetti | Both terminal note callbacks are required, including after one fails/retries | `tests/test_graph_shapes.py` |
| Tributaries | Independent leaf, two roots, uneven paths, intentionally scrambled declaration order | `tests/test_graph_shapes.py` |
| Native Braid | Two agents active together in each round; command joins wait for both | `tests/test_frontier.py` |
| Loom | Overlapping diamonds join, fork into two leaves, and wait for a separate root leaf | `tests/test_generated_graphs.py` |

The first five exercise serial topology by default. Confetti's `prompt` leaves
are performed by the host, using the emitted `result_file` and `complete` argv.
They do not run themselves through `run`. Tests submit deterministic fixture
results so they can prove transitions without launching models.

For Native Braid initialize with `--max-active 2 --shared-workspace-disjoint`.
Use the driver skill to claim, prepare, launch, record and collect native agents.
Tests simulate host handles explicitly; a live pilot is separate evidence.
The shared-workspace flag means each agent writes only its own declared outputs.
Commands and prompt steps remain exclusive even in a concurrent run.

## Prompt entry

Each larger example has a paired `.request.txt`. Use `init --prompt-file` with
an explicitly selected `--backchain-root`. That yields a durable planning packet;
the host performs Backchain planning and submits plan/bindings via `accept-plan`.

`tests/test_prompt_examples.py` runs these paths with authored fixture plans and
the real Backchain packager. It checks imported edges and accepted terminal results.
Those fixtures prove the adapter contract, not model planning quality. The prior
native planning pilot is documented in `docs/VALIDATION.md`.

## Focused checks

```sh
python3 -m unittest discover -s tests -p 'test_graph_shapes.py' -v
python3 -m unittest discover -s tests -p 'test_prompt_examples.py' -v
python3 -m unittest discover -s tests -p 'test_frontier.py' -v
python3 -m unittest discover -s tests -p 'test_generated_graphs.py' -v
python3 -m unittest discover -s tests -p 'test_fault_regressions.py' -v
python3 experiments/graph_matrix.py --seeds 20 --output /tmp/weave-graph-matrix.json
```

The complete suite also covers missing evidence, failed checks, stale callbacks,
output drift, crash recovery, native launch ambiguity, retries and clean-Git run
isolation. Failures remain visible; no example skips a required leaf to finish.
