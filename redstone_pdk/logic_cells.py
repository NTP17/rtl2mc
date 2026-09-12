"""Physical logic/storage macro candidates; admission comes from measured evidence."""
from .repeater_broad_fixtures import rotate, facing_after


def macro(kind):
    body, roles = {}, {}
    def put(x, z, state, role=None):
        p = (x, 0, z)
        if p in body and body[p] != state:
            raise ValueError(f"Conflicting macro blocks at {p}")
        body[p] = state
        if role:
            roles[role] = p
    def wire(x, z):
        put(x, z, "redstone_wire")
    def repeater(x, z, facing, setting=1, role=None):
        put(x, z, f"repeater[facing={facing},delay={setting}]", role)
    if kind in ("NOR2", "INV"):
        for sign, letter in ((-1, "a"), (1, "b")):
            repeater(sign*8, 3, "south", role="entry_"+letter)
            for x in range(2, 9):
                wire(sign*x, 2)
            wire(sign*2, 1); wire(sign*2, 0); wire(sign*8, 4)
            repeater(sign, 0, "west" if sign == -1 else "east", role="side_"+letter)
        put(0, -1, "redstone_block")
        put(0, 0, "comparator[facing=north,mode=subtract]", "nor")
        wire(0, 1); wire(0, 2); wire(0, 4)
        repeater(0, 3, "north", role="output")
        ports = {"A": (-8, 0, 4), "Y": (0, 0, 4)}
        if kind == "NOR2":
            ports["B"] = (8, 0, 4)
        delay = 8
    elif kind == "DFF":
        # Master updates after 4 gt; slave after 2 gt. Clock inversion creates
        # a 2 gt gap on rising edges; the master delay covers overlap on falling edges.
        repeater(-8, 3, "south", role="entry_d"); wire(-8, 4)
        for z in range(-4, 3):
            wire(-8, z)
        for x in range(-7, -1):
            wire(x, -4)
        repeater(-1, -4, "west", 2, "master")
        wire(0, -4); wire(1, -4)
        repeater(2, -4, "west", 1, "slave")
        for x,z in ((3,-4),(3,-3),(3,-2),(2,-2),(1,-2),(0,-2),(0,-1),(0,0),(0,1),(0,2),(0,4)):
            wire(x,z)
        repeater(0, 3, "north", role="output")
        repeater(8, 3, "south", role="entry_clk"); wire(8,4)
        for z in range(-1,3):
            wire(8,z)
        repeater(8,-2,"south",role="clock_common")
        for z in range(-8,-2):
            wire(8,z)
        for x in range(4,8):
            wire(x,-8)
        repeater(3,-8,"east",role="clock_master_route")
        for x in range(-1,3):
            wire(x,-8)
        wire(-1,-7); wire(-1,-6)
        repeater(-1,-5,"north",role="lock_master")
        for x in range(4,8):
            wire(x,-5)
        repeater(3,-5,"east",2,"clock_inverter_input")
        put(2,-6,"redstone_block")
        put(2,-5,"comparator[facing=north,mode=subtract]","lock_slave")
        ports = {"D": (-8,0,4), "CLK": (8,0,4), "Q": (0,0,4)}
        delay = 14
    else:
        raise ValueError("Unknown logic macro")
    return {"kind": kind, "blocks": body, "roles": roles, "ports": ports, "delay_hypothesis": delay}


def place(kind, origin=(24,80,16), rotation=0):
    definition = macro(kind)
    def pos(p):
        x,z = rotate(p[0],p[2],rotation)
        return (origin[0]+x,origin[1]+p[1],origin[2]+z)
    blocks = {}
    for p,state in definition["blocks"].items():
        for facing in ("north","south","east","west"):
            if "facing="+facing in state:
                state = state.replace("facing="+facing,"facing="+facing_after(facing,rotation)); break
        blocks[pos(p)] = state
    return {**definition, "blocks": blocks, "roles": {k:pos(p) for k,p in definition["roles"].items()},
            "ports": {k:pos(p) for k,p in definition["ports"].items()},
            "sources": {k:pos((p[0],p[1],p[2]+1)) for k,p in definition["ports"].items() if k not in ("Y","Q")}}
