"""Replay the 96 fixed lock-sequence fixtures using inspected Java 1.21.1 rules.

This is a deliberately bounded explanation, not a general redstone simulator or
an engine event recorder. See docs/repeater-lock-order-investigation.md.
Only fixture setup/stimulus is used to predict; observations are loaded afterward.
"""

import argparse
from collections import defaultdict
import hashlib
import heapq
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUN = ROOT / "results/20260910T151115Z-97846b"
SERVER_SHA1 = "59353fb40c36d304f2035d51e7d6e6baa98dc05c"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class LockReplay:
    """Two diodes in one loaded chunk, dust input/output, no feedback or backlog."""

    def __init__(self, case, ordering="engine"):
        experiment = case["experiment"]
        self.case = case
        self.ordering = ordering
        self.delay = 2 * experiment["delay_setting"]
        self.side = experiment["side"]
        self.driver = experiment["driver"]
        # Settled fixture initialization, not a value taken from observations.
        self.input = {"dut": experiment["initial_output"], "side": 0}
        self.powered = dict(self.input)
        self.tick = 0
        self.serial = 0
        self.queue = []
        self.pending = set()
        self.remaining_this_tick = set()
        self.events = []
        self.samples = {}

    def record(self, event, **details):
        self.events.append({"tick": self.tick, "event": event, **details})

    def schedule(self, block, delay, priority):
        self.serial += 1  # LevelAccessor creates a sequence number before dedup.
        if block in self.pending:
            self.record("duplicate_ignored", block=block)
            return
        actual_priority = 0 if self.ordering == "uniform_priority" else priority
        order = -self.serial if self.ordering == "reverse_ties" else self.serial
        due = self.tick + delay
        heapq.heappush(self.queue, (due, actual_priority, order, block))
        self.pending.add(block)
        self.record("enqueue", block=block, due=due, priority=actual_priority,
                    sequence=self.serial)

    def neighbor(self, block):
        # RepeaterBlock.isLocked reads the live side signal, not the cached flag.
        if block == "dut" and self.powered["side"]:
            return
        if block in self.remaining_this_tick:
            return  # LevelTicks.willTickThisTick excludes already-dispatched work.
        if self.powered[block] == self.input[block]:
            return
        if block == "dut":
            priority = -2 if self.powered[block] else -1
            delay = self.delay
        else:
            # This side driver's front neighbor is the perpendicular DUT diode.
            priority = -3 if self.driver == "repeater" else -1
            delay = 2
        self.schedule(block, delay, priority)

    def dispatch(self, block, priority, order):
        self.record("dispatch", block=block, priority=priority, order=order,
                    input=self.input[block], powered=self.powered[block],
                    live_lock=self.powered["side"] if block == "dut" else 0)
        if block == "dut" and self.powered["side"]:
            self.record("discard_while_locked", block=block)
            return
        previous = self.powered[block]
        if block == "side" and self.driver == "comparator":
            # Compare mode, rear level 0/15, no alternate input, no container.
            self.powered[block] = self.input[block]
        elif previous and not self.input[block]:
            self.powered[block] = 0
        elif not previous:
            self.powered[block] = 1
            if not self.input[block]:
                self.schedule(block, self.delay if block == "dut" else 2, -2)
        if previous != self.powered[block]:
            self.record("output_change", block=block, value=self.powered[block])
            if block == "side":
                self.neighbor("dut")

    def advance(self, tick):
        self.tick = tick
        collected = []
        while self.queue and self.queue[0][0] <= tick:
            entry = heapq.heappop(self.queue)
            self.pending.remove(entry[3])
            collected.append(entry)
        self.remaining_this_tick = {entry[3] for entry in collected}
        for _, priority, order, block in collected:
            self.remaining_this_tick.remove(block)
            self.dispatch(block, priority, order)

    def command(self, command):
        parts = command.split()
        if len(parts) != 5 or parts[0] != "setblock":
            raise ValueError(f"Unsupported stimulus: {command}")
        position = tuple(map(int, parts[1:4]))
        side_source = (10, 80, 2 if self.side == "north" else 8)
        block = {(8, 80, 5): "dut", side_source: "side"}[position]
        value = {"minecraft:redstone_block": 1, "minecraft:air": 0}[parts[4]]
        self.input[block] = value
        self.record("source_command", block=block, value=value)
        self.neighbor(block)

    def sample(self, tick, phase):
        self.samples[(tick, phase)] = {
            "input": self.input["dut"] * 15,
            "powered": self.powered["dut"],
            "locked": self.powered["side"],
            "out": self.powered["dut"] * 15,
            f"{self.side}_input": self.input["side"] * 15,
            f"{self.side}_powered": self.powered["side"],
        }

    def run(self):
        self.sample(-1, "baseline_before_stimulus")
        for tick in range(self.case["ticks"] + 1):
            self.advance(tick)
            commands = self.case["actions"].get(str(tick), [])
            if tick > 0 and commands:
                self.sample(tick, "before_action")
            for command in commands:
                self.command(command)
            self.sample(tick, "after_commands_or_completed_tick")
        return self


def investigate(run):
    metadata = json.loads((run / "metadata.json").read_text())
    if metadata["server_sha1"] != SERVER_SHA1:
        raise ValueError("This replay is specific to the pinned Java 1.21.1 server.")
    fixtures = json.loads((run / "fixtures.json").read_text())
    fixtures = [f for f in fixtures if f.get("experiment", {}).get("family") == "lock_sequence"]
    if len(fixtures) != 96:
        raise ValueError("Expected the original 96 lock-sequence fixtures.")
    # Generate all predictions before opening the observations file.
    predictions = {mode: {f["id"]: LockReplay(f, mode).run() for f in fixtures}
                   for mode in ("engine", "uniform_priority", "reverse_ties")}
    observed = defaultdict(list)
    with (run / "observations.jsonl").open() as stream:
        for line in stream:
            row = json.loads(line)
            if row["case"] in predictions["engine"]:
                observed[row["case"]].append(row)
    comparisons = {}
    for mode, cases in predictions.items():
        compared_samples = 0
        differences = []
        for fixture, replay in cases.items():
            rows = observed[fixture]
            keys = [(r["relative_game_tick"], r["phase"]) for r in rows]
            if len(keys) != len(set(keys)) or set(keys) != set(replay.samples):
                raise ValueError(f"Missing or duplicate samples: {fixture}")
            for row, key in zip(rows, keys):
                compared_samples += 1
                predicted = replay.samples[key]
                if predicted != row["values"]:
                    differences.append({"fixture": fixture, "tick": key[0], "phase": key[1],
                                        "predicted": predicted, "observed": row["values"]})
        mismatched = {d["fixture"] for d in differences}
        comparisons[mode] = {"matching_cases": len(cases) - len(mismatched),
                             "total_cases": len(cases), "compared_samples": compared_samples,
                             "mismatching_samples": len(differences), "differences": differences}
    examples = {}
    for driver in ("repeater", "comparator"):
        fixture = f"repeater_lockseq_d2_q0_north_{driver}_release_at_due"
        examples[fixture] = predictions["engine"][fixture].events
    return {
        "status": "bounded_code_derived_replay_not_engine_instrumentation",
        "server_sha1": SERVER_SHA1,
        "evidence": {name: sha256(run / name) for name in
                     ("metadata.json", "fixtures.json", "observations.jsonl")},
        "replay_sha256": sha256(Path(__file__)),
        "comparisons": comparisons,
        "example_predicted_event_traces": examples,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path,
                        default=ROOT / ".local/investigation/lock-order-replay.json")
    args = parser.parse_args()
    result = investigate(args.run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for mode, comparison in result["comparisons"].items():
        print(f"{mode}: {comparison['matching_cases']}/{comparison['total_cases']} cases, "
              f"{comparison['compared_samples']} samples, "
              f"{comparison['mismatching_samples']} mismatching samples")
    if result["comparisons"]["engine"]["mismatching_samples"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
