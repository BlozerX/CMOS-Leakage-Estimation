from .spice import ROOT, MODEL, OUT, read_wrdata, run, write_json, manifest, include_path
import numpy as np
import pandas as pd


def main():
    dest = OUT / "milestone"
    dest.mkdir(parents=True, exist_ok=True)
    # The original loop is intentionally retained to measure its true endpoints.
    original = (ROOT / "22n_NMOS_ON.net").read_text()
    net = dest / "22n_NMOS_ON_path_fixed.net"
    model_include = include_path(MODEL, net)
    lines = original.splitlines()
    lines = [f'.include "{model_include}"' if s.upper().startswith('.INCLUDE') else s for s in lines]
    text = "\n".join(lines)
    text = text.replace('.CONTROL', '.CONTROL\nset width=240\nset numdgt=15\nset wr_singlescale\nset wr_vecnames')
    text = text.replace('\nend', '\n  wrdata legacy.dat v(ref) v(drain) v(gate) v(source) v(body) i(vd) i(vg) i(vs) i(vb)\n  set appendwrite\nend')
    text = text.replace('.ENDC', 'show mn\nshowmod mn\nquit\n.ENDC')
    net.write_text(text + "\n")
    (dest / "legacy.dat").unlink(missing_ok=True)
    log = run(net)
    a = read_wrdata(dest / "legacy.dat")
    legacy_residual = float(np.max(np.abs(a[:, 6:].sum(axis=1))))
    # Tighten convergence in an explicitly separate working copy; preserve baseline.
    text = text.replace('.OPTIONS GMIN=1e-020 ABSTOL=1e-18',
                        '.OPTIONS GMIN=1e-020 ABSTOL=1e-20 RELTOL=1e-9 VNTOL=1e-12')
    text = text.replace('legacy.dat', 'verified.dat')
    (dest / 'verified.dat').unlink(missing_ok=True)
    verified_net = dest / '22n_NMOS_ON_verified.net'
    verified_net.write_text(text + '\n')
    log = run(verified_net)
    a = read_wrdata(dest / 'verified.dat')
    df = pd.DataFrame(a, columns=["temperature_C", "Vref_V", "Vd_V", "Vg_V", "Vs_V", "Vb_V",
                                 "I_Vd_A", "I_Vg_A", "I_Vs_A", "I_Vb_A"])
    for t in "dgsb":
        df[f"I{t}_into_device_A"] = -df[f"I_V{t}_A"]
    currents = df[[f"I{t}_into_device_A" for t in "dgsb"]].values
    df["KCL_residual_A"] = currents.sum(axis=1)
    df["Vds_V"] = df.Vd_V - df.Vs_V
    df["Vgs_V"] = df.Vg_V - df.Vs_V
    assert np.max(np.abs(df[["Vd_V", "Vs_V", "Vb_V"]].values)) < 1e-12
    assert np.allclose(df.Vg_V, df.Vref_V, atol=1e-12)
    # BSIM4v5 internal body resistors incur sub-fA cancellation at tiny voltages.
    # Demand <0.01% normalized terminal imbalance, plus a 1 aA absolute floor.
    assert np.all(np.abs(df.KCL_residual_A) < 1e-18 + 1e-4 * np.abs(currents).sum(axis=1))
    # Compare identical biases with gate tunnelling disabled in a separate model copy.
    model_off = dest / "22nm_gate_tunnelling_disabled.pm"
    model_off.write_text(MODEL.read_text().replace("igcmod  = 1", "igcmod  = 0").replace("igbmod  = 1", "igbmod  = 0"))
    off = text.replace(model_include, model_off.name).replace("verified.dat", "gate_disabled.dat")
    (dest / "gate_disabled.dat").unlink(missing_ok=True)
    off_net = dest / "gate_tunnelling_disabled.net"
    off_net.write_text(off + "\n")
    run(off_net)
    offdata = read_wrdata(dest / "gate_disabled.dat")
    report = manifest() | {"row_count": len(df), "bias_points": sorted(df.Vref_V.unique().tolist()),
        "temperatures_C": sorted(df.temperature_C.unique().tolist()),
        "max_KCL_residual_A": float(np.max(np.abs(df.KCL_residual_A))),
        "path_only_copy_max_KCL_residual_A": legacy_residual,
        "max_normalized_KCL_residual": float(np.max(np.abs(df.KCL_residual_A) / np.maximum(np.abs(currents).sum(axis=1), 1e-18))),
        "max_gate_current_A": float(np.max(np.abs(df.Ig_into_device_A))),
        "max_gate_current_tunnelling_disabled_A": float(np.max(np.abs(offdata[:, 7]))),
        "warnings": sorted(set(x for x in log.splitlines() if "warning" in x.lower())),
        "passed": True}
    df.to_csv(dest / "terminal_currents.csv", index=False, float_format="%.16e")
    write_json(dest / "verification.json", report)
    print(report)


if __name__ == "__main__":
    main()
