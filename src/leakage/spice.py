from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "model/model/22nm_MGK.pm"
OUT = ROOT / "generated"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def include_path(model, netlist):
    """SPICE resolves includes from the netlist's working directory."""
    return Path(os.path.relpath(model, Path(netlist).parent)).as_posix()


def simulator():
    candidates = [os.environ.get("NGSPICE"), shutil.which("ngspice_con"),
                  shutil.which("ngspice"), str(Path.home() / "Downloads/ngspice-43_64/Spice64/bin/ngspice_con.exe")]
    for item in candidates:
        if item and Path(item).is_file():
            return str(Path(item).resolve())
    raise RuntimeError("NGSPICE not found. Set NGSPICE to the console executable.")


def run(netlist: Path, timeout=120):
    """Retain netlist and all output, reject simulator errors even with exit 0."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    proc = subprocess.run([simulator(), "-b", netlist.name], cwd=netlist.parent,
                          capture_output=True, text=True, timeout=timeout,
                          creationflags=flags)
    log = proc.stdout + "\n" + proc.stderr
    netlist.with_suffix(".log").write_text(log, encoding="utf-8")
    errors = re.findall(r"^.*(?:fatal|error:|unknown parameter|no such vector|failed).*$", log, re.I | re.M)
    if proc.returncode or errors:
        record = {"netlist": netlist.relative_to(ROOT).as_posix(), "returncode": proc.returncode, "errors": errors}
        with (OUT / "failures.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        raise RuntimeError(f"NGSPICE failure: {netlist}; see {netlist.with_suffix('.log')}")
    return log


def read_wrdata(path):
    """wr_singlescale, wr_vecnames: skip repeated text headers; require finite data."""
    import numpy as np
    rows = []
    for line in Path(path).read_text().splitlines():
        try:
            row = [float(v) for v in line.split()]
        except ValueError:
            continue
        if row:
            rows.append(row)
    data = np.asarray(rows)
    if data.ndim != 2 or not len(data) or not np.isfinite(data).all():
        raise ValueError(f"Invalid exported data: {path}")
    return data


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def manifest():
    import platform
    import numpy
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    version = subprocess.run([simulator(), "--version"], capture_output=True, text=True,
                             creationflags=flags).stdout
    return {"simulator": Path(simulator()).name, "simulator_version": version,
            "python": platform.python_version(), "numpy": numpy.__version__,
            "model": MODEL.relative_to(ROOT).as_posix(), "model_sha256": sha256(MODEL),
            "supplied_netlist_sha256": sha256(ROOT / "22n_NMOS_ON.net"),
            "pdf_sha256": sha256(ROOT / "Project-1_leakage_estimation_annotated.pdf")}
