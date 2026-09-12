"""Physical route tiles: regeneration, stairs, and independent crossings."""
from .fixtures import LAB_BOUNDS
from .logic_fixtures import command, source
from .repeater_broad_fixtures import rotate, facing_after


def route_case(kind, initial=0, rotation=0):
    body, ports = {}, {}
    def put(x,y,z,state):
        p = (x,y,z)
        if p in body and body[p] != state:
            raise ValueError(f"Route collision at {p}")
        body[p] = state
    def wire(x,y,z):
        put(x,y,z,"redstone_wire"); put(x,y-1,z,"stone")
    def rep(x,y,z,facing,delay=1):
        put(x,y,z,f"repeater[facing={facing},delay={delay}]"); put(x,y-1,z,"stone")
    if kind in ("crossing","ascending"):
        wire(6,80,16); rep(7,80,16,"west")
        for x in range(8,56):
            if x in (18,30,42): rep(x,80,16,"west")
            else: wire(x,80,16)
        rep(56,80,16,"west"); wire(57,80,16)
        sources = {"A":(5,80,16)}
        ports = {"a":(6,80,16),"y":(57,80,16)}
        delays = {"y":("A",10)}
        if kind == "ascending":
            # Root x=24 on the lower bus; ascend toward the upper northbound pin.
            for i in range(1,5):
                wire(24,80+i,16-i)
            for z in range(1,12):
                if z == 7: rep(24,84,z,"south")
                else: wire(24,84,z)
            rep(24,84,0,"south"); wire(24,84,-1)
            ports["branch"] = (24,84,-1); delays["branch"] = ("A",8)
    elif kind == "descending":
        wire(24,84,-2); rep(24,84,-1,"north")
        for z in range(13):
            if z == 8: rep(24,84,z,"north")
            else: wire(24,84,z)
        for i in range(1,5):
            wire(24,84-i,12+i)
        for sign in (-1,1):
            for step in range(1,22):
                x=24+sign*step
                if step in (3,15): rep(x,80,16,"west" if sign==1 else "east")
                else: wire(x,80,16)
        # Last dust ports after both regenerated branches.
        sources = {"A":(24,84,-3)}; ports={"a":(24,84,-2),"y":(45,80,16),"branch":(3,80,16)}
        delays={"y":("A",8),"branch":("A",8)}
    else:
        raise ValueError("Unknown route tile")
    if kind == "crossing":
        wire(32,84,-2); rep(32,84,-1,"north")
        for z in range(33):
            if z in (10,22): rep(32,84,z,"north")
            else: wire(32,84,z)
        rep(32,84,33,"north"); wire(32,84,34)
        sources["B"]=(32,84,-3); ports["b"]=(32,84,-2); ports["other"]=(32,84,34); delays["other"]=("B",8)
    def point(p):
        x,z=rotate(p[0]-32,p[2]-16,rotation)
        return (32+x,p[1],16+z)
    rotated={}
    for p,s in body.items():
        for facing in ("north","south","east","west"):
            if "facing="+facing in s:
                s=s.replace("facing="+facing,"facing="+facing_after(facing,rotation)); break
        rotated[point(p)]=s
    sources={k:point(p) for k,p in sources.items()}; ports={k:point(p) for k,p in ports.items()}
    old={"A":initial&1}
    if "B" in sources: old["B"]=(initial>>1)&1
    changes=[(0,{"A":1-old["A"]}),(24,{"A":old["A"]}),(48,{"A":1-old["A"]}),(72,{"A":old["A"]})]
    if "B" in sources:
        changes += [(12,{"B":1-old["B"]}),(36,{"B":old["B"]}),(48,{"B":1-old["B"]}),(84,{"B":old["B"]})]
    events={}
    for t,v in sorted(changes,key=lambda event:event[0]): events.setdefault(t,{}).update(v)
    ticks=max(events)+14
    f={"id":f"map_route_{kind}_r{rotation}_q{initial}","component":"dust","lab_bounds":[list(p) for p in LAB_BOUNDS],
       "setup":[command(p,s) for p,s in sorted(rotated.items(),key=lambda item:item[0][1])],
       "prepare":[{"commands":[source(sources[k],v) for k,v in old.items()],"settle_game_ticks":32}],
       "actions":{t:[source(sources[k],v) for k,v in changes.items()] for t,changes in events.items()},
       "ticks":ticks,"probes":[{"name":k,"position":list(p),"block":"minecraft:redstone_wire","property":"power","values":list(range(16))} for k,p in ports.items()],
       "trace_probes":list(ports),"checks":[],"experiment":{"kind":kind,"rotation":rotation,"initial":old,"events":list(events.items()),"delays":delays}}
    def bit(pin,t):
        v=old[pin]
        for tick,changes in events.items():
            if tick<=t: v=changes.get(pin,v)
        return v
    # Dust output taps may be attenuated. Both directions retain HIGH, while
    # receivers on crossing/ascending outputs restore it to 15.
    gains={"y":10,"branch":10} if kind=="descending" else {"y":15,"branch":15,"other":15}
    expected=[]
    for t in range(-1,ticks+1):
        values={k.lower():15*bit(k,t) for k in sources}
        values.update({k:gains[k]*bit(pin,t-d) for k,(pin,d) in delays.items()})
        expected.append({"tick":t,"values":values})
    f["baseline_checks"]=expected[0]["values"]; f["checks"]=expected[1:]
    return f


def route_cases():
    return [route_case(kind,q,r) for kind in ("crossing","ascending","descending") for r in range(4)
            for q in range(4 if kind=="crossing" else 2)]
