"""Apply quartus/ip/hps_sys/ddr3_overlay to a freshly generated hps_sys (see the README there) and check the result.

qsys-generate exits with errors on this machine because the HPS DDR3 sequencer step crashes; everything else is generated.
This script (1) insists that every reported error belongs to that step, (2) copies the overlay files, (3) appends the .qip lines
the failed step did not write, (4) checks that every file the .qip names exists."""
import os
import re
import shutil
import sys

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "quartus", "ip", "hps_sys")
SYN = os.path.join(ROOT, "hps_sys", "synthesis")
SUB = os.path.join(SYN, "submodules")
OVL = os.path.join(ROOT, "ddr3_overlay")


def main():
    log = open(os.path.join(ROOT, "qsys_generate.log"), errors="replace").read().splitlines()
    errs = [l for l in log if " Error" in l]
    other = [l for l in errs if not any(k in l for k in ("generate_hps_sdram.tcl", "border", "Generation stopped", "qsys-generate failed",
                                                          "seq", "hps_sdram", "uniphy", "alt0", "Nios II", "make all", "child process"))]
    if other:
        print("unexpected errors in qsys_generate.log (not the known DDR3 sequencer step):")
        print("\n".join(other[:10]))
        return 1
    for name in sorted(os.listdir(OVL)):
        p = os.path.join(OVL, name)
        if os.path.isfile(p) and name not in ("README.md", "qip_lines.txt"):
            shutil.copy2(p, os.path.join(SUB, name))
    os.makedirs(os.path.join(SUB, "sequencer"), exist_ok=True)
    for name in os.listdir(os.path.join(OVL, "sequencer")):
        shutil.copy2(os.path.join(OVL, "sequencer", name), os.path.join(SUB, "sequencer", name))
    qip_path = os.path.join(SYN, "hps_sys.qip")
    qip = open(qip_path).read()
    add = [l for l in open(os.path.join(OVL, "qip_lines.txt")).read().splitlines() if l and l not in qip]
    if add:
        with open(qip_path, "a", newline="\n") as f:
            f.write("# DDR3 sequencer step of qsys-generate fails on this machine: lines added from ddr3_overlay/qip_lines.txt\n")
            f.write("\n".join(add) + "\n")
    missing = []
    for m in re.finditer(r'qip_path\) "([^"]+)"', open(qip_path).read()):
        rel = m.group(1)
        if not os.path.exists(os.path.normpath(os.path.join(SYN, rel))):
            missing.append(rel)
    # the reference qip also points MISC_FILEs outside the tree (qsys file, cmp): only the sources matter
    missing = [m for m in missing if m.startswith("submodules/") or m.endswith((".v", ".sv", ".hex", ".sdc", ".tcl"))]
    # every hps_sys_* module that is instantiated must be defined by some file (the failed run also skips ordinary modules)
    defined, used = set(), set()
    for root, _, names in os.walk(SYN):
        for n in names:
            if n.endswith((".v", ".sv")):
                t = re.sub(r"//.*", "", open(os.path.join(root, n), errors="ignore").read())
                defined |= set(re.findall(r"^\s*module\s+(\w+)", t, re.M))
                used |= set(re.findall(r"^\s*(hps_sys_\w+)\s*(?:#\s*\(.*?\)\s*)?\w+\s*\(", t, re.M | re.S))
    undefined = sorted(used - defined)
    missing += ["module " + u for u in undefined]
    print("overlay applied: %d qip line(s) added; %d referenced file(s) / module(s) missing" % (len(add), len(missing)))
    for m in missing[:20]:
        print("  missing:", m)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
