"""PDF configurations plus a rail-gated, independent drain/source-bias dataset."""
import itertools
from pathlib import Path
import numpy as np
import pandas as pd
from .spice import MODEL, OUT, ROOT, run, read_wrdata, write_json, manifest, sha256, include_path

TEMPS = [-40, -20, 0, 20, 30, 45, 60, 75, 90, 105, 125]
WIDTHS_NM = [44, 88, 132]
LENGTHS_NM = [22, 26, 30]
COMPONENTS = ['id', 'igs', 'igd', 'igcs', 'igcd', 'igb', 'ibd', 'ibs', 'isub', 'igidl', 'igisl', 'gds']
VECTORS = ['v(d)', 'v(g)', 'v(s)', 'v(b)', 'i(vd)', 'i(vg)', 'i(vs)', 'i(vb)']
VECTORS += [f'@m1[{c}]' for c in COMPONENTS]
COLS = ['sweep_V', 'Vd_V', 'Vg_V', 'Vs_V', 'Vb_V', 'I_Vd_A', 'I_Vg_A', 'I_Vs_A', 'I_Vb_A']
COLS += [f'bsim_{c}_A' if c!='gds' else 'bsim_gds_S' for c in COMPONENTS]


def header(kind, width, length, sources, netlist):
    return f'''* Generated isolated {kind}; dimensions and terminal order in SI
.include "{include_path(MODEL, netlist)}"
.options gmin=1e-20 abstol=1e-20 reltol=1e-9 vntol=1e-12
M1 d g s b {kind} W={width}n L={length}n AD={width*44}e-18 AS={width*44}e-18 PD={2*(width+44)}n PS={2*(width+44)}n
{sources}
.save all {' '.join('@m1['+c+']' for c in COMPONENTS)}
.control
set numdgt=15
set wr_singlescale
set wr_vecnames
'''


def decode(data, kind, width, length):
    df = pd.DataFrame(data, columns=COLS)
    df['device_type'] = kind
    df['W_nm'] = width
    df['L_nm'] = length
    df['model_sha256'] = sha256(MODEL)
    for t in 'dgsb':
        df[f'I{t}_A'] = -df[f'I_V{t}_A']
    df['Vds_V'] = df.Vd_V-df.Vs_V
    df['Vgs_V'] = df.Vg_V-df.Vs_V
    df['Vbs_V'] = df.Vb_V-df.Vs_V
    df['KCL_residual_A'] = df[['Id_A','Ig_A','Is_A','Ib_A']].sum(axis=1)
    return df


def four_configurations():
    folder = OUT / 'characterization/pdf_configs'
    folder.mkdir(parents=True, exist_ok=True)
    configurations = {
        'NMOS_cond': ('nmos', 'Vref ref 0 0\nVd d 0 0\nVg g ref 0\nVs s 0 0\nVb b 0 0', 1),
        'NMOS_int': ('nmos', 'Vref ref 0 0\nVd d ref 0\nVg g 0 0\nVs s 0 0\nVb b 0 0', 1),
        'PMOS_cond': ('pmos', 'Vref ref 0 0\nVd d ref 0\nVg g 0 0\nVs s ref 0\nVb b ref 0', 1),
        'PMOS_int': ('pmos', 'Vref ref 0 0\nVd d ref 0\nVg g 0 0\nVs s 0 0\nVb b ref 0', -1),
    }
    frames = []
    for config, (kind, sources, polarity) in configurations.items():
        for width, length in itertools.product(WIDTHS_NM, LENGTHS_NM):
            stem = f'{config}_W{width}_L{length}'
            net = folder / f'{stem}.net'
            dat = folder / f'{stem}.dat'
            dat.unlink(missing_ok=True)
            text = header(kind, width, length, sources, net)
            for temp in TEMPS:
                text += f'set temp={temp}\ndc Vref 0 {polarity} {polarity*.025}\nwrdata {stem}.dat {" ".join(VECTORS)}\nset appendwrite\n'
            text += 'quit\n.endc\n.end\n'
            net.write_text(text)
            run(net)
            df = decode(read_wrdata(dat), kind, width, length)
            assert len(df) == len(TEMPS)*41
            df['temperature_C'] = np.repeat(TEMPS, 41)
            df['configuration'] = config
            df['bias_magnitude_V'] = np.abs(df.sweep_V)
            df['netlist'] = net.relative_to(ROOT).as_posix()
            df['netlist_sha256'] = sha256(net)
            frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df.to_csv(OUT / 'datasets/pdf_configurations.csv', index=False, float_format='%.15e')
    print(f'Four configurations: {len(df)} rows', flush=True)
    return df


def general_biases():
    # Canonical variables: distance from body rail. PMOS is mirrored to real rails.
    # Fixed gate rails are sufficient for static logic; analog interstage gates
    # are validated separately and their rail approximation is explicitly audited.
    folder = OUT / 'characterization/general'
    folder.mkdir(parents=True, exist_ok=True)
    source_fractions = [0, .001, .005, .02, .05, .1, .2, .3, .5, .7, .9, .95, .98, .995, .999, 1]
    splits = {
        'train': ([.7, .8, .9], [-40, 0, 30, 60, 90, 125]),
        'validation': ([.75], [45]),
        'test': ([.85], [105]),
    }
    frames = []
    for split, (supplies, temps) in splits.items():
        for kind, vdd, temp in itertools.product(['nmos','pmos'], supplies, temps):
            width = 44 if kind == 'nmos' else 88
            stem = f'{kind}_{split}_V{vdd}_T{temp}'
            net, dat = folder/f'{stem}.net', folder/f'{stem}.dat'
            dat.unlink(missing_ok=True)
            text = header(kind, width, 22, 'Vd d 0 0\nVg g 0 0\nVs s 0 0\nVb b 0 0', net)
            text += f'set temp={temp}\nalter Vb={0 if kind=="nmos" else vdd}\n'
            for gate, sf in itertools.product([0,1], source_fractions):
                s = sf*vdd if kind=='nmos' else (1-sf)*vdd
                g = gate*vdd if kind=='nmos' else (1-gate)*vdd
                start,stop,step = (0,vdd,vdd/40) if kind=='nmos' else (vdd,0,-vdd/40)
                text += f'alter Vs={s:.16g}\nalter Vg={g:.16g}\ndc Vd {start:.16g} {stop:.16g} {step:.16g}\nwrdata {stem}.dat {" ".join(VECTORS)}\nset appendwrite\n'
            text += 'quit\n.endc\n.end\n'
            net.write_text(text)
            run(net)
            df = decode(read_wrdata(dat), kind, width, 22)
            assert len(df)==2*len(source_fractions)*41
            df['temperature_C'], df['VDD_V'], df['split'] = temp, vdd, split
            df['configuration'] = 'independent_drain_source_rail_gate'
            df['netlist'], df['netlist_sha256'] = net.relative_to(ROOT).as_posix(), sha256(net)
            frames.append(df)
        print(f'General biases: {split} complete', flush=True)
    df = pd.concat(frames, ignore_index=True)
    df.to_csv(OUT/'datasets/general_devices.csv', index=False, float_format='%.15e')
    return df


def main():
    if not (OUT/'milestone/verification.json').exists():
        raise RuntimeError('Run and pass the single-device milestone first.')
    (OUT/'datasets').mkdir(parents=True, exist_ok=True)
    four = four_configurations()
    general = general_biases()
    metadata = manifest() | {
        'units': {'voltage':'V','current':'A; positive into device','temperature':'degrees C',
                  'W_nm':'nm','L_nm':'nm','power':'W'},
        'ranges_pdf': {'bias_V':[0,1,.025], 'temperatures_C':TEMPS,
                       'W_nm':WIDTHS_NM,'L_nm':LENGTHS_NM},
        'geometry': 'AD=AS=W*44nm, PD=PS=2*(W+44nm); fixed diffusion length 44 nm',
        'pdf_rows':len(four),'general_rows':len(general),
        'general_split':general.groupby('split').size().to_dict(),
        'split_rule':'General-device split holds out complete (VDD,T) conditions across all terminals and configurations.',
        'model_scope':'Only supplied 22nm_MGK, no process variation; geometry deterministic.',
        'warnings':sorted(set(line for p in (OUT/'characterization').rglob('*.log') for line in p.read_text().splitlines() if 'warning' in line.lower())),
        'max_KCL_residual_A':float(max(four.KCL_residual_A.abs().max(),general.KCL_residual_A.abs().max())),
    }
    write_json(OUT/'datasets/metadata.json',metadata)
    print(f'Completed {len(four)+len(general)} simulated device rows', flush=True)


if __name__=='__main__':
    main()
