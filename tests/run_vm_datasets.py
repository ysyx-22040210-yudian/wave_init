#!/usr/bin/env python3
"""Check an existing interface fixture and a user's local PicoRV32 RTL."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parent.parent


def command(args, cwd, log):
    with log.open("w") as f:
        p=subprocess.run([str(a) for a in args],cwd=str(cwd),stdout=f,stderr=subprocess.STDOUT,timeout=180)
    if p.returncode:
        raise RuntimeError("{}: exit {}\n{}".format(log,p.returncode,log.read_text(errors="replace")[-7000:]))
    return log.read_text(errors="replace")


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--picorv32",required=True)
    p.add_argument("--interface-fixture",required=True)
    args=p.parse_args()
    picorv32=Path(args.picorv32).resolve()
    existing=Path(args.interface_fixture).resolve()
    run=Path(tempfile.mkdtemp(prefix="datasets_",dir=str(ROOT/"build")))
    evidence=[]
    for inst,keys in (("u_src",{"rst_n","sel","a","b","bus.clk"}),
                      ("u_sink",{"rst_n","bus.clk","bus.data"})):
        out=run/inst
        command([sys.executable,ROOT/"wave_init.py","--fsdb",existing/"out/waves.fsdb",
                 "--kdb",existing/"out/simv.daidir","--scope","if_root_tb."+inst,"--time","16ns","--out",out],
                ROOT,run/(inst+".log"))
        r=json.loads((out/"snapshot.json").read_text())
        ss={x["logical_path"].split("if_root_tb."+inst+".",1)[1]:x for x in r["signals"]}
        assert set(ss)==keys
        if inst=="u_sink":assert ss["bus.data"]["value_bin"]=="10100101"
        fl=run/(inst+".f");fl.write_text(str(existing/"if_root_tb.sv")+"\n")
        text=command(["bash",out/"run_vcs.sh",fl],ROOT,out/"replay.log")
        assert "WAVE_INIT_SNAPSHOT_PASS" in text
        evidence.append({"dataset":"existing_interface_port_root","scope":"if_root_tb."+inst,"signals":len(ss),"status":"pass"})

    fixture=run/"picorv32";fixture.mkdir()
    pli=Path(os.environ["VERDI_HOME"])/"share/PLI/VCS/LINUX64"
    command(["vcs","-full64","-sverilog","-debug_access+all","-kdb","-lca",
             "-P",pli/"novas.tab",pli/"pli.a",picorv32,ROOT/"tests/fixtures/picorv32_snapshot_tb.sv",
             "-top","picorv32_snapshot_tb","-o","simv"],fixture,fixture/"compile.log")
    command([fixture/"simv"],fixture,fixture/"simulation.log")
    out=run/"picorv32_snapshot"
    command([sys.executable,ROOT/"wave_init.py","--fsdb",fixture/"waves.fsdb","--kdb",fixture/"simv.daidir",
             "--scope","picorv32_snapshot_tb.dut","--time","26ns","--out",out],ROOT,run/"picorv32_snapshot.log")
    result=json.loads((out/"snapshot.json").read_text())
    expected={"clk":"1","resetn":"1","mem_ready":"1","mem_rdata":format(0x13,"032b"),
              "pcpi_wr":"0","pcpi_rd":format(0x12345678,"032b"),"pcpi_wait":"0","pcpi_ready":"0","irq":"0"*32}
    values={r["port"]:r["value_bin"] for r in result["signals"]}
    assert values==expected,(values,expected)
    fl=run/"picorv32.f";fl.write_text(str(picorv32)+"\n")
    text=command(["bash",out/"run_vcs.sh",fl],ROOT,out/"replay.log")
    assert "WAVE_INIT_SNAPSHOT_PASS" in text
    evidence.append({"dataset":"PicoRV32","source":str(picorv32),"scope":"picorv32_snapshot_tb.dut", "signals":len(values),"parameters":len(result["parameters"]),"status":"pass"})
    (run/"results.json").write_text(json.dumps(evidence,indent=2)+"\n")
    print(json.dumps(evidence,indent=2))
    print("RESULTS "+str(run))


if __name__=="__main__":main()
