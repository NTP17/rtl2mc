"""Arc-delay and missing-SDF controls, separate from settled circuit tests."""
from pathlib import Path
import subprocess
from tools.eda_tools import runtime
from .mapping_views import KINDS,DELAYS,sdf
from .rtl import dump,sha


def artifacts():
    components = [{"name":"c_"+k.lower(),"kind":k,"delay":DELAYS[k]} for k in KINDS]
    lines = ["`timescale 1ns/1ps", "module arc_bank_mapped(input A,B,D,CLK);"]
    for k in KINDS:
        name = "c_"+k.lower()
        lines.append(f"  wire q_{k.lower()};")
        pins = ".D(D),.CLK(CLK),.Q(q_dff)" if k == "DFF" else ".A(A),"+(".B(B)," if k=="NOR2" else "")+f".Y(q_{k.lower()})"
        lines.append(f"  RMAP_{k} {name}({pins});")
    lines += ["endmodule", "module arc_tb;", "  reg A=0, B=0, D=0, CLK=0;", "  arc_bank_mapped dut(A,B,D,CLK);",
              "  initial begin", "`ifndef NO_ANNOTATE", '    $sdf_annotate("arc.sdf",dut);', "`endif", "  end",
              "  initial begin", "    #40; A=1; CLK=1; #40; A=0; CLK=0; #20; D=1; #20; B=1; CLK=1; #40; B=0; CLK=0; #20; D=0; #20; CLK=1;", "  end", "  initial begin"]
    previous = 0
    sample_times = sorted(set([30,60,100,180,230]+[base+off for base in (40,80,120,160,200) for off in range(17)]))
    for t in sample_times:
        lines.append(f"    #{t+.001-previous:.3f};"); previous=t+.001
        for k in KINDS:
            if k == "DFF":
                if t < 60: continue
                q = int(134<=t<214)
            elif k == "NOR2":
                q = int(not (48<=t<88 or 128<=t<168))
            elif k == "INV": q = int(not (48<=t<88))
            else: q = int(40+DELAYS[k]<=t<80+DELAYS[k])
            lines.append(f'    if (dut.q_{k.lower()} !== 1\'b{q}) $fatal(1,"RMAP_ARC_MISMATCH {k} t={t}");')
    lines += ['    $display("RMAP_ARCS_PASS"); $finish;', "  end", "endmodule", "",
              "module width_tb;", "  reg A=0,B=0,D=0,CLK=0;", "  arc_bank_mapped dut(A,B,D,CLK);",
              '  initial $sdf_annotate("arc.sdf",dut);',
              '  always @(dut.c_dff.notifier) if ($time > 90) begin $display("RMAP_WIDTH_CAUGHT"); $finish; end',
              '  initial begin #40; CLK=1; #40; CLK=0; #40; CLK=1; #5; CLK=0; #30; $fatal(1,"RMAP_WIDTH_NOT_ENFORCED"); end',
              "endmodule", ""]
    return {"arc.sdf":sdf({"top":"arc_bank"},{"components":components}),"arc-bench.sv":"\n".join(lines)}


def check(folder):
    folder = Path(folder)
    for name,content in artifacts().items():
        (folder/name).write_text(content,encoding="utf-8",newline="\n")
    rt = runtime(); records = []
    for mode in ("specify","sdf","missing_sdf","portable"):
        flags = ["-g2012","-s","arc_tb"]
        cells = "cells-portable.sv" if mode == "portable" else "cells-timing.sv"
        if mode != "portable": flags += ["-gspecify"]
        if mode in ("sdf","missing_sdf"): flags += ["-DRMAP_SDF_ONLY"]
        if mode != "sdf": flags += ["-DNO_ANNOTATE"]
        p = subprocess.run([str(rt["iverilog"]),*flags,"-o","arc.vvp",cells,"arc-bench.sv"],cwd=folder,env=rt["env"],capture_output=True,text=True,timeout=60)
        if p.returncode: raise ValueError(p.stdout+p.stderr)
        r = subprocess.run([str(rt["vvp"]),"arc.vvp"],cwd=folder,env=rt["env"],capture_output=True,text=True,timeout=60)
        log = p.stdout+p.stderr+r.stdout+r.stderr
        (folder/f"arc-{mode}.log").write_text(log,encoding="utf-8",newline="\n")
        expected_failure = mode == "missing_sdf"
        if expected_failure:
            if r.returncode==0 or "RMAP_ARC_MISMATCH" not in log: raise ValueError("Missing-SDF control did not fail")
        elif r.returncode or "RMAP_ARCS_PASS" not in log: raise ValueError("Arc control failed in "+mode+": "+log[-500:])
        records.append({"mode":mode,"expected_failure":expected_failure,"pass":True,"log_sha256":sha(folder/f"arc-{mode}.log")})
    report = {"pass":True,"checks":records,"width_timingcheck_execution":"commercial tools required; Icarus does not implement TIMINGCHECK"}
    dump(folder/"arc-report.json",report)
    return report
