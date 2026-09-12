"""Deterministic two-level bus router with extracted wire/strength checks.

Coordinates are blocks. Logic is at y=84, buses at y=80. All routing is static.
The router deliberately trades area and speed for inspectable construction.
"""
from collections import defaultdict, deque
import re

from .logic_cells import place

FACING = {(1,0,0): "west", (-1,0,0): "east", (0,0,1): "north", (0,0,-1): "south"}


def add(a,b):
    return tuple(x+y for x,y in zip(a,b))


def line(a,b):
    axis = next(i for i in range(3) if a[i] != b[i])
    if any(a[i] != b[i] for i in range(3) if i != axis):
        raise ValueError("Route segment must be axis aligned")
    step = 1 if b[axis] > a[axis] else -1
    return [tuple(a[j] if j != axis else v for j in range(3)) for v in range(a[axis], b[axis]+step, step)]


def route(graph):
    blocks, tags, components, sources, outputs, pins = {}, {}, [], [], [], {}
    net_sources, net_sinks = {}, defaultdict(list)
    seq = 0
    def fresh():
        nonlocal seq
        value = f"w{seq:04d}"; seq += 1
        return value
    def put(p,state):
        if p in blocks and blocks[p] != state:
            raise ValueError(f"Block collision at {p}: {blocks[p]} versus {state}")
        blocks[p] = state
    def tag(p,node):
        if p in tags and tags[p] != node:
            raise ValueError(f"Routing short at {p}")
        tags[p] = node; put(p,"redstone_wire")
    slot = 0
    for name, port in graph["ports"].items():
        if port["direction"] != "input":
            continue
        for i,bit in enumerate(port["bits"]):
            x = 280+24*slot; slot += 1
            pin, a, src = (x,84,20), (x,84,18), (x,84,17)
            node, raw = fresh(), fresh()
            tag(pin,node); tag(a,raw)
            put((x,84,19),"repeater[facing=north,delay=1]")
            label = f"in_{name}_{i}"
            sources.append({"name":label,"port":name,"bit_index":i,"logical_bit":bit,"position":src,"probe":a,"wire":raw})
            components.append({"name":label,"kind":"BUF2","pins":{"A":raw,"Y":node},"position":(x,84,19),"delay":2})
            net_sources[bit] = (pin,node)
    macro_records = []
    for n in graph["cells"]:
        origin = (280+24*slot,84,16); slot += 1
        cell = place(n["kind"],origin)
        for p,s in cell["blocks"].items():
            put(p,s)
        cp = {}
        for name,bit in n["pins"].items():
            p = cell["ports"][name]
            if name in ("Y","Q"):
                node = fresh(); tag(p,node); cp[name] = node; net_sources[bit] = (p,node)
            else:
                net_sinks[bit].append((n["name"],name,p))
        components.append({"name":n["name"],"kind":n["kind"],"pins":cp,"position":origin,
                           "delay":cell["delay_hypothesis"]})
        macro_records.append({"name":n["name"],"kind":n["kind"],"origin":origin,
                              "ports":cell["ports"],"roles":cell["roles"]})
    for name, port in graph["ports"].items():
        if port["direction"] != "output":
            continue
        for i,bit in enumerate(port["bits"]):
            x = 280+24*slot; slot += 1
            label = f"out_{name}_{i}"
            a,y = (x,84,20),(x,84,18)
            node = fresh(); tag(y,node)
            put((x,84,19),"repeater[facing=south,delay=1]")
            components.append({"name":label,"kind":"BUF2","pins":{"Y":node},"position":(x,84,19),"delay":2})
            net_sinks[bit].append((label,"A",a))
            outputs.append({"name":label,"port":name,"bit_index":i,"position":y,"wire":node,"logical_bit":bit})
    for bit in ("0","1"):
        if net_sinks[bit]:
            x = 280+24*slot; slot += 1
            node, raw = fresh(), fresh()
            p = (x,84,20); tag(p,node); tag((x,84,18),raw)
            put((x,84,19),"repeater[facing=north,delay=1]")
            if bit == "1":
                put((x,84,17),"redstone_block")
            label = "const_"+bit
            sources.append({"name":label,"constant":int(bit),"position":(x,84,17),"probe":(x,84,18),"wire":raw})
            components.append({"name":label,"kind":"BUF2","pins":{"A":raw,"Y":node},"position":(x,84,19),"delay":2})
            net_sources[bit] = (p,node)
    component_by_name = {c["name"]:c for c in components}
    def path(points,node,reps):
        for i,p in enumerate(points):
            if p in reps:
                if i == 0 or i == len(points)-1:
                    raise ValueError("Repeater cannot terminate a route")
                direction = tuple(b-a for a,b in zip(points[i-1],p))
                if direction not in FACING or add(p,direction) != points[i+1]:
                    raise ValueError("Repeater requires a flat, straight segment")
                nxt = fresh(); label = f"r{len(components):04d}"
                put(p,f"repeater[facing={FACING[direction]},delay=1]")
                c = {"name":label,"kind":"BUF2","pins":{"A":node,"Y":nxt},"position":p,"delay":2}
                components.append(c); component_by_name[label] = c
                node = nxt
            else:
                tag(p,node)
        return node
    clock = graph["clock_bit"]
    net_keys = sorted((b for b in net_sinks if net_sinks[b]), key=lambda b:(b==clock,str(b)))
    route_records = []
    for ni,bit in enumerate(net_keys):
        source,node = net_sources[bit]
        z = 88+8*ni
        # Source column descends onto its bus. Last repeater supplies the staircase.
        end = (source[0],84,z-4)
        upper = line(source,end)
        repz = set(range(26,z-7,8))
        repz = {v for v in repz if z-6-v >= 3}; repz.add(z-6)
        stair = [(source[0],84-i,z-4+i) for i in range(1,5)]
        base = path(upper+stair,node,{(source[0],84,v) for v in repz})
        sink_base = {}
        for sign in (-1,1):
            xs = [p[2][0] for p in net_sinks[bit] if (p[2][0]-source[0])*sign > 0]
            if not xs:
                continue
            xmax = min(xs) if sign == -1 else max(xs)
            points = line((source[0],80,z),(xmax,80,z))
            reps = {(source[0]+sign*d,80,z) for d in range(3,abs(xmax-source[0]),8)}
            path(points,base,reps)
            for x in xs:
                sink_base[x] = tags[(x,80,z)]
        for label,pin,target in net_sinks[bit]:
            x = target[0]
            node0 = base if x == source[0] else sink_base[x]
            stair = [(x,80+i,z-i) for i in range(5)]
            upper = line((x,84,z-4),target)[1:]
            repz = set(range(z-5,24,-8))
            repz = {v for v in repz if v-22 >= 3}; repz.add(22)
            result = path(stair+upper,node0,{(x,84,v) for v in repz})
            component_by_name[label]["pins"][pin] = result
        route_records.append({"logical_bit":bit,"bus_z":z,"source":source,
                              "sinks":[{"cell":a,"pin":b,"position":c} for a,b,c in net_sinks[bit]]})
    # Balance the clock tree by extending existing receiver-column repeaters.
    raw_clocks = [s["wire"] for s in sources if s.get("logical_bit") == clock] if clock is not None else []
    def arrivals(start):
        arrival = {start:0}; parent = {}
        todo = [c for c in components if c["kind"].startswith("BUF")]
        while todo:
            ready = [c for c in todo if c["pins"]["A"] in arrival]
            if not ready: break
            for c in ready:
                y = c["pins"]["Y"]
                arrival[y] = arrival[c["pins"]["A"]]+c["delay"]; parent[y] = c; todo.remove(c)
        return arrival,parent
    clock_delay = 0
    if raw_clocks:
        arrival,parent = arrivals(raw_clocks[0])
        ff = [c for c in components if c["kind"] == "DFF"]
        clock_delay = max(arrival[c["pins"]["CLK"]] for c in ff)
        for c in ff:
            wire = c["pins"]["CLK"]; extra = clock_delay-arrival[wire]
            target_x = next(m["ports"]["CLK"][0] for m in macro_records if m["name"] == c["name"])
            while extra:
                b = parent.get(wire)
                if b is None or b["position"][0] != target_x or b["position"][1] != 84:
                    raise ValueError("Clock tree requires more delay capacity than the receiver column provides")
                inc = min(extra,6); b["delay"] += inc; b["kind"] = f"BUF{b['delay']}"
                blocks[b["position"]] = re.sub(r"delay=\d",f"delay={b['delay']//2}",blocks[b["position"]])
                extra -= inc; wire = b["pins"]["A"]
        arrival,_ = arrivals(raw_clocks[0])
        if {arrival[c["pins"]["CLK"]] for c in ff} != {clock_delay}:
            raise ValueError("Clock balancing failed")
    # Rigid support below every component/dust; crossings keep intervening air.
    for p in list(blocks):
        support = add(p,(0,-1,0))
        if support in blocks and blocks[support] != "stone":
            raise ValueError("A support block would overwrite a circuit element")
        put(support,"stone")
    bounds = [[min(p[i] for p in blocks)-(2 if i != 1 else 0) for i in range(3)],
              [max(p[i] for p in blocks)+(2 if i != 1 else 1) for i in range(3)]]
    data = {"schema_version":1,"top":graph["top"],"bounds":bounds,"clock_delay":clock_delay,
            "blocks":[{"position":p,"state":s} for p,s in sorted(blocks.items())],
            "wires":[{"position":p,"net":n} for p,n in sorted(tags.items())],
            "components":components,"macros":macro_records,"sources":sources,"outputs":outputs,"routes":route_records}
    data["drc"] = check_layout(data)
    return data


def check_layout(layout):
    """Re-extract dust connectivity and strength from blocks, not route lengths."""
    blocks = {tuple(b["position"]):b["state"] for b in layout["blocks"]}
    wires = {tuple(w["position"]):w["net"] for w in layout["wires"]}
    if len(blocks) != len(layout["blocks"]) or len(wires) != len(layout["wires"]):
        raise ValueError("Duplicate block or wire record")
    allowed = set(wires)
    allowed.update(tuple(c["position"]) for c in layout["components"] if c["kind"].startswith("BUF"))
    allowed.update(tuple(s["position"]) for s in layout["sources"] if s.get("constant") == 1)
    for p in wires:
        if blocks.get(p) != "redstone_wire" or blocks.get(add(p,(0,-1,0))) != "stone":
            raise ValueError("Missing wire or support")
    # Recheck every exact macro body and rigid support.
    for m in layout["macros"]:
        body = place(m["kind"],m["origin"])
        allowed.update(body["blocks"])
        if body["ports"] != {k:tuple(v) for k,v in m["ports"].items()}:
            raise ValueError("Macro pin definition differs")
        for p,s in body["blocks"].items():
            if blocks.get(p) != s or blocks.get(add(p,(0,-1,0))) != "stone":
                raise ValueError("Macro differs from measured arrangement")
    allowed.update(add(p,(0,-1,0)) for p in list(allowed))
    if set(blocks) != allowed:
        raise ValueError("Layout contains unregistered or missing blocks")
    neighbors = defaultdict(set)
    for p,n in wires.items():
        for dx,dz in ((1,0),(-1,0),(0,1),(0,-1)):
            for dy in (-1,0,1):
                q = add(p,(dx,dy,dz))
                if q not in wires: continue
                # A stair connects only if the higher dust's supporting block
                # has free headroom over the lower dust.
                low = p if dy >= 0 else q
                if dy and blocks.get(add(low,(0,1,0)),"air") != "air": continue
                if wires[q] != n:
                    raise ValueError(f"Unintended dust connection {p} -> {q}")
                neighbors[p].add(q)
    groups = defaultdict(set)
    for p,n in wires.items(): groups[n].add(p)
    seeds,receivers = defaultdict(list),[]
    for s in layout["sources"]:
        seeds[s["wire"]].append(tuple(s["probe"]))
    by_name = {m["name"]:m for m in layout["macros"]}
    for c in layout["components"]:
        if c["kind"].startswith("BUF"):
            p = tuple(c["position"]); state = blocks.get(p,"")
            match = re.fullmatch(r"repeater\[facing=(\w+),delay=([1-4])\]",state)
            if not match or 2*int(match[2]) != c["delay"] or c["kind"] != f"BUF{c['delay']}":
                raise ValueError("Route repeater setting mismatch")
            d = next(k for k,v in FACING.items() if v == match[1])
            a,y = add(p,tuple(-i for i in d)),add(p,d)
            if wires.get(a) != c["pins"]["A"] or wires.get(y) != c["pins"]["Y"]:
                raise ValueError("Repeater pin extraction mismatch")
            for side in ((d[2],0,-d[0]),(-d[2],0,d[0])):
                if blocks.get(add(p,side),"air") != "air":
                    raise ValueError("Route repeater has an unintended side neighbor")
            if blocks.get(add(p,(0,-1,0))) != "stone":
                raise ValueError("Repeater has no support")
            seeds[c["pins"]["Y"]].append(y); receivers.append((c["name"],a,c["pins"]["A"]))
        else:
            m = by_name[c["name"]]
            for pin,node in c["pins"].items():
                p = tuple(m["ports"][pin])
                if wires.get(p) != node: raise ValueError("Macro pin net differs")
                if pin in ("Y","Q"): seeds[node].append(p)
                else: receivers.append((c["name"]+"."+pin,p,node))
    levels, max_span = {}, 0
    for net,points in groups.items():
        if len(seeds[net]) != 1:
            raise ValueError(f"Require exactly one driver for wire segment {net}")
        start = seeds[net][0]; distances = {start:0}; todo = deque([start])
        while todo:
            p = todo.popleft()
            for q in neighbors[p]:
                if q not in distances:
                    distances[q] = distances[p]+1; todo.append(q)
        if set(distances) != points:
            raise ValueError("Disconnected wire segment "+net)
        max_span = max(max_span,max(distances.values()))
        for p,d in distances.items(): levels[p] = max(0,15-d)
    minimum = 15
    for name,p,net in receivers:
        if levels.get(p,0) < 1:
            raise ValueError("Insufficient redstone strength at "+name)
        minimum = min(minimum,levels[p])
    # The DRC certificate includes actual HIGH levels at boundary probes.
    for o in layout["outputs"]:
        if wires.get(tuple(o["position"])) != o["wire"]:
            raise ValueError("Output probe differs")
    return {"pass":True,"wire_segments":len(groups),"routed_receivers":len(receivers),
            "minimum_receiver_high":minimum,"maximum_dust_distance":max_span,
            "blocks":len(blocks),"route_repeaters":sum(c["kind"].startswith("BUF") for c in layout["components"]),
            "scope":"exact macro bodies, dust connectivity, directed repeater pins, single drivers, strength, support and route side isolation"}
