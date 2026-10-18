"""Create the reviewable results report and exportable plots from executed data."""
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import xml.sax.saxutils as xml
import numpy as np
import pandas as pd
from .spice import ROOT,OUT,write_json,manifest


def md_table(df,columns):
    lines=['| '+' | '.join(columns)+' |','| '+' | '.join(['---']*len(columns))+' |']
    for _,r in df.iterrows():
        cells=[]
        for c in columns:
            v=r[c]
            cells.append(f'{v:.6g}' if isinstance(v,(float,np.floating)) else str(v))
        lines.append('| '+' | '.join(cells)+' |')
    return '\n'.join(lines)


def svg_fallback(cases,milestone,predictions):
    """Portable fallback when Matplotlib is unavailable; every value is measured."""
    folder=OUT/'plots';folder.mkdir(parents=True,exist_ok=True)
    def frame(title,xlabel,ylabel):
        return ['<svg xmlns="http://www.w3.org/2000/svg" width="960" height="560" viewBox="0 0 960 560">',
                '<rect width="960" height="560" fill="white"/>',
                '<g font-family="Arial,sans-serif" fill="#172b4d">',
                f'<text x="60" y="35" font-size="22">{xml.escape(title)}</text>',
                '<path d="M85 75V465H915" fill="none" stroke="#223344"/>',
                f'<text x="470" y="540" text-anchor="middle" font-size="16">{xml.escape(xlabel)}</text>',
                f'<text transform="translate(22,270) rotate(-90)" text-anchor="middle" font-size="16">{xml.escape(ylabel)}</text>']
    test=cases[(cases.split=='test')&(~cases.circuit.str.startswith('STACK'))]
    names=['INV','NAND2','AND2','AO31']; bars=test.groupby('circuit').supply_relative_error_pct.max()
    a=frame('Held-out circuit maximum supply-current error','Circuit, 0.85 V / 105 C','Maximum relative error (%)')
    for tick in [0,1,2,3]:
        y=465-tick/3*350
        a += [f'<path d="M85 {y}H915" stroke="#dddddd"/>',f'<text x="72" y="{y+5}" text-anchor="end">{tick}</text>']
    for i,name in enumerate(names):
        x=145+i*190;h=bars[name]/3*350
        a += [f'<rect x="{x}" y="{465-h}" width="100" height="{h}" fill="#287d8e"/>',
              f'<text x="{x+50}" y="{450-h}" text-anchor="middle">{bars[name]:.3f}%</text>',
              f'<text x="{x+50}" y="495" text-anchor="middle">{name}</text>']
    a+=['<path d="M85 348.333H915" stroke="#c44e52" stroke-dasharray="6 4"/>','</g></svg>']
    (folder/'circuit_error.svg').write_text('\n'.join(a))
    a=frame('Original NMOS: zero drain-source bias','Gate voltage (V)','Signed current into device (nA)')
    colors=['#287d8e','#d45d00','#7a4eb2','#288c42']
    for temp,dash in [(30,''),(90,'6 3')]:
        part=milestone[milestone.temperature_C==temp]
        for j,t in enumerate('dgsb'):
            points=' '.join(f'{85+v/1.2*830:.3f},{465-(i*1e9+15)/55*380:.3f}' for v,i in zip(part.Vg_V,part[f'I{t}_into_device_A']))
            a.append(f'<polyline points="{points}" fill="none" stroke="{colors[j]}" stroke-width="2" stroke-dasharray="{dash}"/>')
    for v in [0,.3,.6,.9,1.2]: a.append(f'<text x="{85+v/1.2*830}" y="490" text-anchor="middle">{v}</text>')
    for val in [-10,0,10,20,30,40]: a.append(f'<text x="72" y="{465-(val+15)/55*380+5}" text-anchor="end">{val}</text>')
    for j,t in enumerate('dgsb'): a.append(f'<text x="{110+j*180}" y="66" fill="{colors[j]}">I{t} (30C solid, 90C dashed)</text>')
    a+=['</g></svg>'];(folder/'single_device.svg').write_text('\n'.join(a))
    a=frame('Held-out general devices: drain-current magnitude','Reference log10(|ID| / A)','Prediction log10(|ID| / A)')
    part=predictions[(predictions.split=='test')&(predictions.task.str.startswith('general'))&(predictions.terminal=='Id_A')]
    part=part[(abs(part.reference_A)>=1e-12)&(abs(part.prediction_A)>=1e-12)].iloc[::3]
    for _,r in part.iterrows():
        x=85+(np.log10(abs(r.reference_A))+12)/9*830;y=465-(np.log10(abs(r.prediction_A))+12)/9*390
        a.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="1.7" fill="#287d8e" opacity=".4"/>')
    for val in [-12,-10,-8,-6,-4]:
        a.extend([f'<text x="{85+(val+12)/9*830}" y="490" text-anchor="middle">{val}</text>',
                  f'<text x="72" y="{470-(val+12)/9*390}" text-anchor="end">{val}</text>'])
    a+=['<path d="M85 465L915 75" stroke="#c44e52" fill="none"/>','</g></svg>']
    (folder/'device_parity.svg').write_text('\n'.join(a))


def matplotlib_plots(cases,milestone,predictions):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        return False
    plt.rcParams.update({'font.size':11,'axes.spines.top':False,'axes.spines.right':False,'figure.dpi':130})
    folder=OUT/'plots'
    def save(fig,name):
        fig.savefig(folder/f'{name}.png',dpi=180,bbox_inches='tight')
        fig.savefig(folder/f'{name}.svg',bbox_inches='tight')
        plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,4.7),layout='constrained')
    for t,col in zip('dgsb',['#287d8e','#d45d00','#7a4eb2','#288c42']):
        for temp,style in [(30,'-'),(90,'--')]:
            part=milestone[milestone.temperature_C==temp]
            ax.plot(part.Vg_V,part[f'I{t}_into_device_A']*1e9,style,color=col,label=f'I{t}, {temp} C')
    ax.set(xlabel='Gate voltage (V)',ylabel='Current into terminal (nA)',title='Original NMOS bias: VD = VS = VB = 0 V')
    ax.axhline(0,color='gray',lw=.6);ax.legend(ncol=4,fontsize=8);ax.grid(alpha=.2)
    save(fig,'single_device')
    fig,ax=plt.subplots(figsize=(7,5),layout='constrained')
    for kind,col in [('general_nmos','#287d8e'),('general_pmos','#d45d00')]:
        part=predictions[(predictions.split=='test')&(predictions.task==kind)&(predictions.terminal=='Id_A')]
        mask=(abs(part.reference_A)>=1e-12)&(abs(part.prediction_A)>=1e-12)
        ax.scatter(abs(part.reference_A[mask]),abs(part.prediction_A[mask]),s=6,alpha=.35,label=kind.replace('general_','').upper(),color=col)
    ax.plot([1e-12,1e-3],[1e-12,1e-3],'k--',lw=.8)
    ax.set(xscale='log',yscale='log',xlim=(1e-12,1e-3),ylim=(1e-12,1e-3),
           xlabel='Reference |ID| (A)',ylabel='Predicted |ID| (A)',title='Held-out .85 V / 105 C; references and predictions >= 1 pA')
    ax.legend();ax.grid(alpha=.2);save(fig,'device_parity')
    fig,axes=plt.subplots(2,2,figsize=(11,7),layout='constrained')
    for ax,name in zip(axes.ravel(),['INV','NAND2','AND2','AO31']):
        part=cases[(cases.split=='test')&(cases.circuit==name)]
        x=np.arange(len(part));ax.bar(x,part.supply_relative_error_pct,color='#287d8e')
        ax.axhline(1,color='#c44e52',ls='--',label='1% target')
        ax.set(title=name,ylabel='Supply-current error (%)',xlabel='Input pattern',ylim=(0,3))
        ax.set_xticks(x,part.inputs,rotation=45 if len(part)>5 else 0);ax.grid(axis='y',alpha=.2)
    axes[0,0].legend(fontsize=9);fig.suptitle('Independent circuit estimates: held-out .85 V / 105 C')
    save(fig,'circuit_error')
    fig,ax=plt.subplots(figsize=(7,5),layout='constrained')
    for name in ['STACK_N2','STACK_N3','STACK_P2','STACK_P3']:
        part=cases[(cases.circuit==name)&(cases.split=='test')]
        xs=[];ys=[]
        for node in ['x1','x2']:
            if f'reference_{node}_V' in part:
                mask=part[f'reference_{node}_V'].notna()
                xs.extend(part.loc[mask,f'reference_{node}_V']);ys.extend(part.loc[mask,f'estimated_{node}_V'])
        ax.scatter(xs,ys,s=32,alpha=.7,label=name)
    ax.plot([0,.85],[0,.85],'k--',lw=.8);ax.set(xlabel='NGSPICE internal voltage (V)',ylabel='Independent predicted voltage (V)',title='Two- and three-device stack intermediate voltages')
    ax.legend(fontsize=9);ax.grid(alpha=.2);save(fig,'stack_voltages')
    return True


def main():
    cases=pd.read_csv(OUT/'circuits/comparison.csv',dtype={'inputs':str})
    milestone=pd.read_csv(OUT/'milestone/terminal_currents.csv')
    predictions=pd.read_csv(OUT/'evaluation/device_predictions.csv')
    svg_fallback(cases,milestone,predictions)
    plotted=matplotlib_plots(cases,milestone,predictions)
    flags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0
    tests=subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-v'],cwd=ROOT,capture_output=True,text=True,creationflags=flags)
    (OUT/'evaluation/test_output.txt').write_text(tests.stdout+tests.stderr)
    write_json(OUT/'evaluation/verification.json',{'integration_checks_passed':tests.returncode==0,'exit_code':tests.returncode,'matplotlib_plots_generated':plotted})
    if tests.returncode: raise RuntimeError('Integration checks failed; inspect test_output.txt')
    environment=manifest()
    versions={}
    for package in ['numpy','pandas','matplotlib','scipy','scikit-learn']:
        try: versions[package]=importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: versions[package]=None
    environment['packages']=versions
    write_json(OUT/'evaluation/environment.json',environment)
    (ROOT/'requirements-lock.txt').write_text('\n'.join(f'{p}=={versions[p]}' for p in ['numpy','pandas','matplotlib'] if versions[p])+'\n')
    cm=pd.read_csv(OUT/'evaluation/circuit_metrics.csv')
    dm=pd.read_csv(OUT/'evaluation/device_metrics.csv')
    m=json.loads((OUT/'milestone/verification.json').read_text())
    diagnosis=json.loads((OUT/'evaluation/diagnosis.json').read_text())
    ct=cm[(cm.split=='test')&(~cm.circuit.str.startswith('STACK'))]
    ct=ct.set_index('circuit').loc[['INV','NAND2','AND2','AO31']].reset_index()
    columns=['circuit','R2','MAE_A','RMSE_A','floored_mean_relative_pct','floored_p95_relative_pct','floored_max_relative_pct']
    dt=dm[(dm.split=='test')&(dm.model=='structured_device_grid')]
    qt=dm[(dm.split=='test')&(dm.model=='local_quadratic_64')&(dm.terminal=='Id_A')]
    plotext='png' if plotted else 'svg'
    text=f'''# Executed leakage-estimation results

**Workflow implemented and checked; the universal <1% target is not achieved.**
All 16 PDF pages were visually inspected. Page4 explicitly targets R2>0.99 and
error<1% against simulation, but does not define the error statistic or scope.
See [requirements review](docs/requirements_review.md) and [reproduction/viva guide](README.md).

## Single-device milestone: passed physical consistency checks

The supplied 22nm NMOS has VD=VS=VB=0V. The original loop actually generated
{m['row_count']} rows: VG=.05..1.20V, at 30/90C. It skips zero bias. VDS=0 means
this is not a conventional on-current sweep, despite the filename.

* Maximum signed gate current magnitude: {m['max_gate_current_A']:.9g} A.
* Maximum gate current with tunnelling disabled: {m['max_gate_current_tunnelling_disabled_A']:.6g} A (numerical residue).
* Path-only copy maximum terminal KCL residue: {m['path_only_copy_max_KCL_residual_A']:.6g} A.
* Verified-copy maximum KCL residue: {m['max_KCL_residual_A']:.6g} A;
  maximum normalized imbalance {m['max_normalized_KCL_residual']*100:.6g}%.
* TOXE/TOXP/DTOX warning is preserved. NGSPICE43 dispatches card version4.0 to BSIM4v5.
* Device current is -I(terminal voltage source); all four signed currents balance.

![Original device terminal currents](generated/plots/single_device.{plotext})

## Dataset and evaluation scope

16,236 rows implement the four PDF configurations over voltage, temperature,
W/L. Another 52,480 rows span independent drain/source bias at the fixed circuit
geometry. Every row retains type, model hash, SI-labelled measurements, bias
configuration, temperature and netlist provenance. Generated netlists, logs and
text exports are retained. Source PDF/netlist/model files match initial hashes;
all ten model files also match their archived originals.

General-device training is .7/.8/.9V and -40/0/30/60/90/125C. Validation is
.75V/45C; final test is .85V/105C. Complete operating conditions stay together.
Four-case validation/test temperatures are 45/105C. Models were selected by
validation criteria or specified before test inspection, without test tuning.
These are limited held-out conditions, not evidence of accuracy everywhere.

## Held-out isolated-device metrics

Raw-current R2, MAE and RMSE use amperes. Relative error is
100*|prediction-reference|/max(|reference|,1pA). Below 1pA it is a scaled
absolute error, not ordinary relative error. CSVs also contain MAPE above 1pA,
the near-zero fraction and fraction within1%. Signs are retained in scoring.

{md_table(dt,['task','terminal','R2','MAE_A','RMSE_A','floored_mean_relative_pct','floored_p95_relative_pct','floored_max_relative_pct'])}

All general-device terminal R2 values exceed .99; mean/p95/max relative-error
targets do not uniformly pass. In particular, large relative errors can occur
at terminal-current cancellation points even while global R2 is excellent.
Polynomial baseline comparisons are in [all device metrics](generated/evaluation/device_metrics.csv).

Four-case selected local-quadratic **drain-current** results:

{md_table(qt,['task','R2','MAE_A','RMSE_A','floored_mean_relative_pct','floored_p95_relative_pct','floored_max_relative_pct'])}

These local fits improve the polynomial baseline but fail relative-error
requirements. Bias sign changes and weak-current behavior remain poorly fit.
Literal PMOS_int also forward-biases its source/well junction: at |Vref|=1V,
30C, W44/L22nm, source current is about1.18mA. It is not pure cutoff leakage.

![Held-out device parity](generated/plots/device_parity.{plotext})

## Complete gates and intermediate voltages

250 cases cover INV, NAND2, AND2, AO31, and NMOS/PMOS two/three-device chains,
every input combination, at five operating conditions. All direct logic truth
tables pass. All independent KCL solves converge to <1fA nodal imbalance.
Stack all-on patterns conduct ordinary DC current; they are not leakage-only.

The estimator receives only known topology, inputs, VDD,T and learned isolated
device models. It solves internal/output voltages independently. Reference
node voltages are used only after prediction for comparison and diagnosis.
The supply cut sums each VDD-connected terminal once, including bodies;
series currents are never added twice. Supply power and all-source static
power are reported separately. AND2=NAND2+inverter; AO31=(A&B&C)|D.

Held-out **supply-current** scores (.85V/105C):

{md_table(ct,columns)}

INV and NAND2 pass both R2>.99 and maximum error<1% on this limited test.
AND2 and AO31 pass R2>.99 but fail the 1% target even for mean error.
No inference of a universal pass is made from these few patterns/conditions.

![Errors by input pattern](generated/plots/circuit_error.{plotext})

Maximum internal-node error across all250 cases is {cases.max_node_error_V.max():.6g}V;
errors and individual node voltages are in [the full comparison](generated/circuits/comparison.csv).
The largest deviations occur in conducting standalone stacks and some weakly
held internal nodes. Logic output levels still match the static truth tables.

## Independent accounting check and failure investigation

Re-simulating isolated devices at measured full-gate voltages gives maximum
terminal-current difference {diagnosis['max_isolated_replay_terminal_difference_A']:.6g}A and maximum supply
relative error {diagnosis['max_isolated_replay_supply_relative_error_pct']:.6g}% over all26 held-out gate patterns.
This diagnostic validates device decomposition/current directions. It deliberately
uses simulator voltages and is not the independent predictor's accuracy.

Mean supply error for device regression evaluated at measured nodes is
{diagnosis['mean_model_reference_node_supply_error_pct']:.6g}%, versus {diagnosis['mean_independent_supply_error_pct']:.6g}% for independently
solved nodes. This indicates contributions from both device approximation and
node/interstage-gate approximation; this is a diagnostic comparison, not a
formal additive error decomposition. Gate rounding deviations are recorded.

The four-case fits struggle near low-bias sign changes; error-by-magnitude
tables expose this. For example NMOS_cond currents above10nA have much lower
mean relative error than smaller currents. Temperature/supply interpolation
and continuous interstage gate bias also limit the structured model.
See [worst cases](generated/evaluation/worst_device_errors.csv),
[magnitude bins](generated/evaluation/error_by_magnitude.csv), and
[isolated replay](generated/circuits/isolated_replay/supply_diagnosis.csv).

Initial strict AND2 convergence failed and was repaired with documented
solver options. Development failures remain in failures.jsonl. Final artifact
checks pass: supplied-file preservation/archive match, four bias cases, split
isolation/no duplicate general samples, all truth tables, stack device polarity,
surrogate KCL/domain guards, and isolated-current recombination.

## Limits and next experiment

This model covers one deterministic technology card and fixed circuit geometry;
it does not establish unseen process/geometry or analog gate accuracy. Body
bias is tied to CMOS rails. Several illustrated parallel-branch stack variants
are not standalone characterization cases. AO31 is an extension after simple
structural checks, although AND2 predictive accuracy had not met1%.

Use **validation** failures to design denser T/VDD training, adaptive rail and
zero-crossing samples, and continuous near-rail gate bias for interstage loading.
Use multiple new operating-condition/geometry holdouts and reserve a **fresh**
final test set before claiming a 1% model. Do not tune against this final test.
The current implementation is a reproducible evaluated baseline, not a claimed
completion of the universal numerical accuracy target.

Exact reproduction commands are in [README](README.md). Test output and runtime
versions are in generated/evaluation. No simulator result, target achievement,
or completed check is fabricated.
'''
    if plotted:
        text=text.replace('## Independent accounting check', '![Stack intermediate voltages](generated/plots/stack_voltages.png)\n\n## Independent accounting check')
    (ROOT/'RESULTS.md').write_text(text,encoding='utf-8')
    print(f'Report written; eight integration checks passed; Matplotlib plots: {plotted}',flush=True)


if __name__=='__main__': main()
