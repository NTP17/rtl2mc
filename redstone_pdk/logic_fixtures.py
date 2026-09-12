"""Logic/FF experiments kept separate from the earlier repeater catalogs."""
from .logic_cells import place
from .fixtures import LAB_BOUNDS


def command(position, state):
    return "setblock "+" ".join(map(str,position))+" minecraft:"+state


def source(position, value):
    return command(position, "redstone_block" if value else "air")


def fixture(kind, name, initial, events, *, rotation=0, ticks=None):
    layout = place(kind, rotation=rotation)
    probes = [{"name": k.lower(), "position": list(p), "block": "minecraft:redstone_wire", "property": "power", "values": list(range(16))}
              for k,p in layout["ports"].items()]
    for role,p in layout["roles"].items():
        block = layout["blocks"][p].split("[")[0]
        probes.append({"name": role+"_q", "position": list(p), "block": "minecraft:"+block, "property": "powered", "values": [False,True]})
        if block == "repeater":
            probes.append({"name": role+"_locked", "position": list(p), "block": "minecraft:"+block, "property": "locked", "values": [False,True]})
    actions = {tick:[source(layout["sources"][p], v) for p,v in changes.items()] for tick,changes in events}
    return {"id":name,"component":"comparator" if kind != "DFF" else "repeater", "lab_bounds":[list(p) for p in LAB_BOUNDS],
            "setup":[command(p,s) for p,s in layout["blocks"].items()],
            "prepare":[{"commands":[source(layout["sources"][p],v) for p,v in initial.items()],"settle_game_ticks":40}],
            "actions":actions,"ticks":ticks if ticks is not None else max(actions)+24,
            "probes":probes,"trace_probes":[p["name"] for p in probes],"checks":[],
            "experiment":{"kind":kind,"rotation":rotation,"initial":initial,"events":[[t,v] for t,v in events]}}


def pilot_cases():
    nor = fixture("NOR2","logic_nor_pilot",{"A":0,"B":0},[(0,{"A":1}), (32,{"A":0,"B":1}), (64,{"A":1}), (96,{"A":0,"B":0})])
    nor["baseline_checks"] = {"y":15}
    nor["checks"] = [{"tick":t,"values":{"y":v}} for t,v in ((7,15),(8,0),(31,0),(40,0),(72,0),(103,0),(104,15),(120,15))]
    nor["edge_hypotheses"] = [{"probe":"y","after":t,"to":v,"delay":8} for t,v in ((0,0),(96,15))]
    ff = fixture("DFF","logic_dff_pilot",{"D":0,"CLK":0},[(0,{"D":1}),(20,{"CLK":1}),(40,{"D":0}),
                 (60,{"CLK":0}),(80,{"CLK":1}),(100,{"D":1}),(120,{"CLK":0}),(140,{"CLK":1}),(180,{"CLK":0})])
    ff["baseline_checks"] = {"q":0}
    ff["checks"] = [{"tick":t,"values":{"q":v}} for t,v in ((10,0),(33,0),(34,15),(59,15),(79,15),(93,15),(94,0),(119,0),(139,0),(153,0),(154,15),(204,15))]
    ff["edge_hypotheses"] = [{"probe":"q","after":t,"to":v,"delay":14} for t,v in ((20,15),(80,0),(140,15))]
    return [nor,ff]


def external_prediction(case):
    """Independent Boolean/edge law at the macro ports, outside its startup hold."""
    exp = case["experiment"]
    history = exp["events"]
    scale = exp.get("input_high", {})
    def inputs(t):
        values = dict(exp["initial"])
        for tick, changes in history:
            if tick <= t:
                values.update(changes)
        return values
    output = "q" if exp["kind"] == "DFF" else "y"
    captures = []
    prior = dict(exp["initial"])
    for tick, changes in history:
        value = {**prior, **changes}
        if exp["kind"] == "DFF" and prior["CLK"] == 0 and value["CLK"] == 1:
            captures.append((tick+14, value["D"]))
        prior = value
    predicted = []
    for t in range(-1,case["ticks"]+1):
        ports = {k.lower():v*scale.get(k,15) for k,v in inputs(t).items()}
        if exp["kind"] == "DFF":
            q = exp.get("initial_q",0)
            for due, value in captures:
                if due <= t:
                    q = value
        else:
            v = inputs(t-8)
            q = int(not (v["A"] or v.get("B",0)))
        ports[output] = 15*q
        predicted.append({"tick":t,"values":ports})
    return predicted


def complete_checks(case):
    expected = external_prediction(case)
    case["baseline_checks"] = expected[0]["values"]
    case["checks"] = expected[1:]
    return case


def logic_cases():
    result = []
    for rotation in range(4):
        for old in range(4):
            for new in range(4):
                if old == new:
                    continue
                result.append(complete_checks(fixture("NOR2",f"map_nor_r{rotation}_{old}_{new}",
                    {"A":old&1,"B":old>>1},[(0,{"A":new&1,"B":new>>1})],rotation=rotation,ticks=12)))
        for initial in (0,1):
            result.append(complete_checks(fixture("INV",f"map_inv_r{rotation}_{initial}",{"A":initial},
                [(0,{"A":1-initial})],rotation=rotation,ticks=12)))
        for period in (9,16,31):
            states = (0,1,2,3,0,3,2,1,0,1,0,2,0,3,0,3,0)
            result.append(complete_checks(fixture("NOR2",f"map_nor_train_r{rotation}_p{period}",{"A":0,"B":0},
                [(i*period,{"A":v&1,"B":v>>1}) for i,v in enumerate(states[1:])],rotation=rotation)))
        for pin in ("A","B"):
            for strength in (1,8,15):
                for initial in (0,1):
                    old = {"A":0,"B":0}; old[pin] = initial
                    f = fixture("NOR2",f"map_nor_strength_r{rotation}_{pin.lower()}_{strength}_q{initial}",old,
                                [(0,{pin:1-initial})],rotation=rotation,ticks=12)
                    layout = place("NOR2",rotation=rotation)
                    port, first = layout["ports"][pin], layout["sources"][pin]
                    vector = tuple(a-b for a,b in zip(first,port))
                    distance = 16-strength
                    endpoint = tuple(a+distance*d for a,d in zip(port,vector))
                    f["setup"] += [command(tuple(a+i*d for a,d in zip(port,vector)),"redstone_wire") for i in range(1,distance)]
                    f["prepare"][0]["commands"] = [source(endpoint if p==pin else layout["sources"][p],v) for p,v in old.items()]
                    f["actions"][0] = [source(endpoint,1-initial)]
                    f["experiment"]["input_high"] = {pin:strength}
                    result.append(complete_checks(f))
        for q0 in (0,1):
            for d0 in (0,1):
                for half in (17,32):
                    events = []
                    for i,d in enumerate((d0,1-d0,d0,1-d0)):
                        events.append((i*2*half,{"CLK":1}))
                        events.append(((2*i+1)*half,{"CLK":0,"D":1-d}))
                    f = fixture("DFF",f"map_ff_r{rotation}_q{q0}_d{d0}_h{half}",{"D":d0,"CLK":0},events,rotation=rotation)
                    initialize_ff(f,q0)
                    result.append(complete_checks(f))
        for polarity in (0,1):
            for setup in (11,12,20):
                for hold in (3,10):
                    f = fixture("DFF",f"map_ff_window_r{rotation}_to{polarity}_s{setup}_h{hold}",{"D":1-polarity,"CLK":0},
                        [(40-setup,{"D":polarity}),(40,{"CLK":1}),(40+hold,{"D":1-polarity}),(72,{"CLK":0})],rotation=rotation)
                    initialize_ff(f,1-polarity)
                    result.append(complete_checks(f))
    return result


def initialize_ff(f, q):
    f["experiment"]["initial_q"] = q
    layout = place("DFF",rotation=f["experiment"]["rotation"])
    f["prepare"] = [
        {"commands":[source(layout["sources"][p],v) for p,v in {"D":q,"CLK":0}.items()],"settle_game_ticks":40},
        {"commands":[source(layout["sources"]["CLK"],1)],"settle_game_ticks":24},
        {"commands":[source(layout["sources"][p],v) for p,v in f["experiment"]["initial"].items()],"settle_game_ticks":40}]
