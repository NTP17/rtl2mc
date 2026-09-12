"""Experimental Java 1.21.1 event model for static, planar repeater fixtures.

Physics is driven by block positions, facing, properties, and commands. Fixture
IDs, experiment labels, expected results, and observations are not model inputs.
See docs/repeater-event-model.md for the deliberately bounded wiring envelope.
"""
from collections import deque
from dataclasses import dataclass, field
import heapq
import re


VECTORS = {"north": (0, 0, -1), "east": (1, 0, 0), "south": (0, 0, 1), "west": (-1, 0, 0)}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}
SIDES = {"north": ("east", "west"), "south": ("west", "east"),
         "east": ("south", "north"), "west": ("north", "south")}
DIODES = ("repeater", "comparator")


class UnsupportedCircuit(ValueError):
    pass


def adjacent(position, direction):
    return tuple(a + b for a, b in zip(position, VECTORS[direction]))


@dataclass
class Block:
    kind: str
    facing: str = "north"
    delay: int = 1
    powered: bool = False
    locked: bool = False
    power: int = 0
    mode: str = "compare"


@dataclass(order=True, frozen=True)
class ScheduledEvent:
    due: int
    priority: int
    order: int
    position: tuple = field(compare=False)
    kind: str = field(compare=False)


class Circuit:
    """Block graph plus per-chunk queues; all represented chunks stay loaded."""

    def __init__(self, support_y=79):
        self.support_y = support_y
        self.blocks = {}
        self.time = 0
        self.serial = 0
        self.queues = {}
        self.pending = set()
        self.remaining = set()
        self.events = []
        self.dispatching = None
        self.source_positions = None

    def validate_topology(self, source_positions):
        """Reject geometry whose update semantics this bounded model omits."""
        self.source_positions = set(source_positions)
        wires = {p for p, b in self.blocks.items() if b.kind == "redstone_wire"}
        components = {}
        unseen = set(wires)
        while unseen:
            first = min(unseen)
            component, todo = set(), [first]
            while todo:
                position = todo.pop()
                if position in component:
                    continue
                component.add(position)
                todo.extend(adjacent(position, d) for d in VECTORS if adjacent(position, d) in wires and adjacent(position, d) not in component)
            unseen -= component
            if len({p[0] for p in component}) > 1 and len({p[2] for p in component}) > 1:
                raise UnsupportedCircuit("This version supports straight planar dust runs, not junctions or bends")
            drivers = set()
            for position in component:
                for direction in VECTORS:
                    candidate = adjacent(position, direction)
                    block = self.at(candidate)
                    if candidate in self.source_positions or block.kind == "redstone_block":
                        drivers.add(candidate)
                    elif block.kind in DIODES and adjacent(candidate, self.output_direction(block)) == position:
                        drivers.add(candidate)
            if len(drivers) > 1:
                raise UnsupportedCircuit("Multiple drivers on a dust net require internal wire update modeling")
            for position in component:
                components[position] = (component, drivers)
        recipients = {}
        for position, block in self.blocks.items():
            if block.kind not in DIODES:
                continue
            rear = adjacent(position, block.facing)
            rear_block = self.at(rear)
            drivers = set(components[rear][1]) if rear in components else set()
            if rear in self.source_positions or rear_block.kind == "redstone_block":
                drivers.add(rear)
            elif rear_block.kind in DIODES and adjacent(rear, self.output_direction(rear_block)) == position:
                drivers.add(rear)
            if block.kind == "comparator":
                if rear in components and len(components[rear][0]) != 1:
                    raise UnsupportedCircuit("Comparator helpers are restricted to binary rear inputs")
                if any(self.at(adjacent(position, d)).kind != "air" or adjacent(position, d) in self.source_positions for d in SIDES[block.facing]):
                    raise UnsupportedCircuit("Comparator side inputs are outside the helper profile")
            else:
                for direction in SIDES[block.facing]:
                    side = adjacent(position, direction)
                    side_block = self.at(side)
                    if side_block.kind in DIODES and adjacent(side, self.output_direction(side_block)) == position:
                        drivers.add(side)
            for driver in drivers:
                recipients.setdefault(driver, set()).add(position)
        if any(len(targets) > 1 for targets in recipients.values()):
            raise UnsupportedCircuit("Independent fanout scheduling ties are outside this version's update-order profile")
        def visit(position, ancestors):
            if position in ancestors:
                raise UnsupportedCircuit("Feedback circuits require additional validation")
            for target in recipients.get(position, ()):
                visit(target, ancestors | {position})
        for driver in recipients:
            visit(driver, set())

    def record(self, event, position=None, **details):
        row = {"tick": self.time, "event": event, **details}
        if position is not None:
            row["position"] = list(position)
        if self.dispatching is not None:
            row["dispatch_order"] = self.dispatching.order
        self.events.append(row)

    def at(self, position):
        return self.blocks.get(position, Block("air"))

    def output_direction(self, block):
        return OPPOSITE[block.facing]

    def signal(self, source, receiver):
        block = self.at(source)
        if block.kind == "redstone_block":
            return 15
        if block.kind == "redstone_wire":
            return block.power
        if block.kind in DIODES and adjacent(source, self.output_direction(block)) == receiver:
            return (15 if block.powered else 0) if block.kind == "repeater" else block.power
        return 0

    def rear(self, position):
        block = self.at(position)
        return self.signal(adjacent(position, block.facing), position)

    def side(self, position, diodes_only=False):
        block = self.at(position)
        levels = []
        for direction in SIDES[block.facing]:
            neighbor = adjacent(position, direction)
            if not diodes_only or self.at(neighbor).kind in DIODES:
                levels.append(self.signal(neighbor, position))
        return max(levels, default=0)

    def is_locked(self, position):
        return self.at(position).kind == "repeater" and self.side(position, True) > 0

    def prioritized(self, position):
        block = self.at(position)
        direction = self.output_direction(block)
        front = self.at(adjacent(position, direction))
        return front.kind in DIODES and front.facing != direction

    def schedule(self, position, delay, priority, reason):
        self.serial += 1
        block = self.at(position)
        key = (position, block.kind)
        self.record("enqueue_request", position, due=self.time + delay, priority=priority,
                    order=self.serial, reason=reason)
        if key in self.pending:
            self.record("duplicate_ignored", position, order=self.serial)
            return
        event = ScheduledEvent(self.time + delay, priority, self.serial, position, block.kind)
        chunk = (position[0] // 16, position[2] // 16)
        heapq.heappush(self.queues.setdefault(chunk, []), event)
        self.pending.add(key)
        self.record("enqueue", position, due=event.due, priority=priority, order=event.order, reason=reason)

    def check_neighbor(self, position):
        block = self.at(position)
        if block.kind not in DIODES:
            return
        if self.is_locked(position):
            return
        if (position, block.kind) in self.remaining:
            return
        if block.kind == "comparator":
            rear, side = self.rear(position), self.side(position)
            output = rear if rear >= side else 0
            on = rear > 0 and rear >= side
            if output != block.power or on != block.powered:
                self.schedule(position, 2, -1 if self.prioritized(position) else 0, "neighbor")
        elif block.powered != (self.rear(position) > 0):
            priority = -3 if self.prioritized(position) else (-2 if block.powered else -1)
            self.schedule(position, 2 * block.delay, priority, "neighbor")

    def refresh(self, changed):
        """Resolve planar dust levels, then notify affected adjacent diodes.

        This resolves each command/block-update boundary synchronously. It does
        not claim to reproduce intermediate dust update order inside that step.
        """
        wires = {p: b for p, b in self.blocks.items() if b.kind == "redstone_wire"}
        levels = {p: 0 for p in wires}
        work = deque()
        for position in wires:
            direct = max((self.signal(adjacent(position, d), position)
                          for d in VECTORS if self.at(adjacent(position, d)).kind != "redstone_wire"), default=0)
            if direct:
                levels[position] = direct
                work.append(position)
        while work:
            position = work.popleft()
            level = levels[position] - 1
            if level <= 0:
                continue
            for direction in VECTORS:
                neighbor = adjacent(position, direction)
                if neighbor in levels and levels[neighbor] < level:
                    levels[neighbor] = level
                    work.append(neighbor)
        changed = set(changed)
        for position, level in levels.items():
            if wires[position].power != level:
                wires[position].power = level
                changed.add(position)
        affected = set()
        for position in changed:
            for direction in VECTORS:
                neighbor = adjacent(position, direction)
                if self.at(neighbor).kind in DIODES:
                    affected.add(neighbor)
        # Repeater LOCKED is refreshed from live physical side signals.
        for position, block in self.blocks.items():
            if block.kind == "repeater":
                block.locked = self.is_locked(position)
        # Corpus wire nets have at most one rear-input recipient. Independent
        # same-update fanout ties are outside this version's supported envelope.
        for position in sorted(affected):
            self.check_neighbor(position)

    def dispatch(self, event):
        position = event.position
        block = self.at(position)
        if block.kind != event.kind:
            raise UnsupportedCircuit("Scheduled component was replaced")
        self.dispatching = event
        locked = self.is_locked(position)
        before = block.powered
        self.record("dispatch", position, due=event.due, priority=event.priority,
                    order=event.order, kind=block.kind, powered=int(before), live_lock=int(locked))
        if locked:
            self.record("discard_while_locked", position)
        else:
            rear = self.rear(position)
            self.record("input_read", position, value=rear)
            if block.kind == "comparator":
                side = self.side(position)
                previous = block.power
                block.power = rear if rear >= side else 0
                block.powered = rear > 0 and rear >= side
                # Compare mode refreshes its front neighbors even at equal output.
                if previous != block.power or block.mode == "compare":
                    self.refresh({position})
            else:
                if block.powered and rear == 0:
                    block.powered = False
                elif not block.powered:
                    block.powered = True
                    if rear == 0:
                        self.schedule(position, 2 * block.delay, -2, "pulse_stretch_return")
                if before != block.powered:
                    self.refresh({position})
            if before != block.powered:
                self.record("output_change", position, value=int(block.powered))
        self.record("dispatch_end", position, powered=int(block.powered))
        self.dispatching = None

    def step(self):
        self.time += 1
        collected = []
        while True:
            eligible = [(queue[0].priority, queue[0].order, chunk) for chunk, queue in self.queues.items()
                        if queue and queue[0].due <= self.time]
            if not eligible:
                break
            _, _, chunk = min(eligible)
            event = heapq.heappop(self.queues[chunk])
            self.pending.remove((event.position, event.kind))
            collected.append(event)
            if len(collected) > 65536:
                raise UnsupportedCircuit("Tick workload exceeds the supported no-backlog envelope")
        self.remaining = {(event.position, event.kind) for event in collected}
        for event in collected:
            self.remaining.remove((event.position, event.kind))
            self.dispatch(event)

    def advance(self, ticks):
        if type(ticks) is not int or ticks < 0:
            raise ValueError("Tick count must be a nonnegative integer")
        for _ in range(ticks):
            self.step()

    def command(self, command, *, setup=False):
        match = re.fullmatch(r"setblock (-?\d+) (-?\d+) (-?\d+) minecraft:([a-z_]+)(?:\[([^]]+)\])?", command)
        if not match:
            raise UnsupportedCircuit(f"Unsupported command: {command}")
        position = tuple(map(int, match.group(1, 2, 3)))
        if position[1] != self.support_y + 1:
            raise UnsupportedCircuit("Only one horizontal layer on rigid support is supported")
        kind = match[4]
        if kind not in (*DIODES, "air", "redstone_block", "redstone_wire"):
            raise UnsupportedCircuit(f"Unsupported block: {kind}")
        properties = dict(item.split("=", 1) for item in match[5].split(",")) if match[5] else {}
        allowed = {"repeater": {"facing", "delay"}, "comparator": {"facing", "mode"}}.get(kind, set())
        if set(properties) - allowed:
            raise UnsupportedCircuit("Forced power/lock state and other block properties are unsupported")
        if not setup and (kind not in ("air", "redstone_block") or self.at(position).kind not in ("air", "redstone_block")):
            raise UnsupportedCircuit("Runtime actions may only toggle fixed source positions")
        if not setup and self.source_positions is not None and position not in self.source_positions:
            raise UnsupportedCircuit("Source position was not declared when validating the topology")
        block = Block(kind, facing=properties.get("facing", "north"), delay=int(properties.get("delay", 1)), mode=properties.get("mode", "compare"))
        if block.facing not in VECTORS or not 1 <= block.delay <= 4 or block.mode != "compare":
            raise UnsupportedCircuit("Unsupported facing, delay, or comparator mode")
        if kind == "air":
            self.blocks.pop(position, None)
        else:
            self.blocks[position] = block
        self.record("command", position, kind=kind)
        self.refresh({position})
        if kind in DIODES:
            self.check_neighbor(position)

    def probe(self, probe):
        block = self.at(tuple(probe["position"]))
        if "minecraft:" + block.kind != probe["block"]:
            raise UnsupportedCircuit(f"Probe does not identify its physical block: {probe['name']}")
        prop = probe["property"]
        if prop not in {"redstone_wire": ("power",), "repeater": ("powered", "locked"), "comparator": ("powered",)}.get(block.kind, ()):
            raise UnsupportedCircuit(f"Unsupported probe: {prop}")
        return int(getattr(block, prop))


def simulate_fixture(fixture):
    """Adapt physical commands/probes only; never read fixture expectations."""
    world = Circuit()
    for command in fixture["setup"]:
        world.command(command, setup=True)
    all_commands = list(fixture["setup"]) + [command for stage in fixture.get("prepare", []) for command in stage["commands"]] + [command for commands in fixture["actions"].values() for command in commands]
    sources = {tuple(map(int, command.split()[1:4])) for command in all_commands
               if command.split()[-1] in ("minecraft:redstone_block", "minecraft:air")}
    world.validate_topology(sources)
    world.advance(20)
    for stage in fixture.get("prepare", []):
        for command in stage["commands"]:
            world.command(command)
        world.advance(stage["settle_game_ticks"])
    origin = world.time
    first_event = len(world.events)
    initial_pending = [{"position": list(e.position), "due": e.due - origin, "priority": e.priority, "order": e.order}
                       for queue in world.queues.values() for e in sorted(queue)]
    samples = []
    def sample(tick, phase):
        samples.append({"relative_game_tick": tick, "phase": phase, "sample_index": len(samples),
                        "values": {probe["name"]: world.probe(probe) for probe in fixture["probes"]}})
    sample(-1, "baseline_before_stimulus")
    actions = {int(tick): commands for tick, commands in fixture["actions"].items()}
    for tick in range(fixture["ticks"] + 1):
        if tick > 0:
            world.step()
        if tick in actions:
            if tick > 0:
                sample(tick, "before_action")
            for command in actions[tick]:
                world.command(command)
        sample(tick, "after_commands_or_completed_tick")
    events = [{**event, "tick": event["tick"] - origin,
               **({"due": event["due"] - origin} if "due" in event else {})} for event in world.events[first_event:]]
    return {"samples": samples, "events": events, "initial_pending_events": initial_pending}
