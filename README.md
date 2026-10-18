# LeakForge

**From transistor physics to learned leakage models.**

A reproducible CMOS leakage laboratory built with NGSPICE and Python:
68,716 device samples, physics-aware regression, independent stack-voltage
solving, and 250 complete-circuit/stack comparisons.

![Held-out circuit accuracy](generated/plots/circuit_error.png)

**Measured, not assumed:** on the held-out 0.85V/105C condition, inverter and
NAND2 supply-current errors stay below 1%; AND2 and AO31 exceed it. All four
gate R2 values exceed .99. The detailed report retains failures and limitations.

## CMOS leakage estimation: NGSPICE + Python

Implemented and simulated using the supplied 22nm_MGK card. Start with
**[RESULTS.md](RESULTS.md)** for measured results/limitations and
[the page-by-page requirements review](docs/requirements_review.md) for the
assignment interpretation. The workflow runs; universal <1% error is **not
achieved**. Every reported value comes from an executed simulation/evaluation.

## Quick start from a fresh clone

Use Python 3.12 and install the NGSPICE console executable (the recorded runs
use NGSPICE 43). On Windows:

```powershell
git clone https://github.com/BlozerX/LeakForge.git
cd LeakForge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock.txt
$env:LEAKAGE_PYTHON = (Get-Command python).Source
$env:NGSPICE = 'C:\Spice64\bin\ngspice_con.exe' # Adjust to your installation
.\run.ps1 all
```

## Run individual stages on Windows

```powershell
.\run.ps1 milestone
.\run.ps1 characterize
.\run.ps1 train
.\run.ps1 circuits
.\run.ps1 diagnostics
.\run.ps1 report
# Or all six stages:
.\run.ps1 all

# Integration verification:
$env:PYTHONPATH = "$PWD\src;$PWD\tools\python-packages"
& "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s tests -v
```

Launcher defaults to bundled Python and the discovered local NGSPICE43 console
executable. Overrides for another machine:

```powershell
$env:LEAKAGE_PYTHON = 'C:\path\to\python.exe'
$env:NGSPICE = 'C:\path\to\ngspice_con.exe'
& $env:LEAKAGE_PYTHON -m pip install -r requirements.txt
.\run.ps1 all
```

Linux/macOS after installing NGSPICE and Python:

```bash
python -m pip install -r requirements.txt
export PYTHONPATH="$PWD/src"
export NGSPICE="$(command -v ngspice)"
for stage in milestone characterize train circuits diagnostics report; do
  python -m leakage.$stage || exit 1
done
python -m unittest discover -s tests -v
```

Use the recorded NGSPICE43 build for close reproduction: another simulator
release may dispatch this old card differently. Regression uses NumPy only;
no optional ML library is required. Matplotlib makes PNG plots if available;
standalone SVG plots are always emitted. Load only trusted pickle model files.
The script creates no global environment changes. File hashes and package
versions identify each run. Exact pins for the final environment are saved
in `generated/evaluation/environment.json` and `requirements-lock.txt`.

Generated netlists use relative model includes and can be run from their own
directories after cloning. Git preserves the exact bytes of supplied inputs
and generated artifacts so recorded SHA-256 provenance survives checkout.
Installed dependencies, Python caches, and private local run archives are
excluded from version control. Supplied course material and transistor model
cards retain their original attribution; no blanket license is applied to them.

## Organization

| Path | Contents |
|---|---|
| Supplied PDF/netlist/model directory/model.tar | Preserved source inputs |
| src/leakage/ | Generation, simulator runner/parser, regressions, circuit KCL solve, diagnostics/report |
| docs/requirements_review.md | All PDF pages, annotations, explicit requirements versus assumptions |
| generated/milestone/ | Path-only and verified copies, tunnelling ablation, logs, CSV, checks |
| generated/characterization/ | Every generated netlist/log/simulator text export |
| generated/datasets/ | 16,236 PDF-case rows, 52,480 general rows, units/hashes/metadata |
| generated/models/ | Trained models, feature definitions/splits/selection metadata |
| generated/circuits/ | 250 gate/stack cases, terminal currents, independent estimates, isolated replay |
| generated/evaluation/ | Metrics, predictions, worst errors, magnitude bins, verification |
| generated/plots/ | Exportable result plots |
| generated/failures.jsonl | Development failure audit, including repaired runs |
| tests/ | Integration checks against actual generated artifacts |

## Milestone 1: explain the supplied netlist

`Mn drain gate source body nmos W=22n L=22n` uses D,G,S,B order, dimensions
22nm in SI units. Model level54/version4.0 is dispatched to **BSIM4v5** by
this NGSPICE43 build. The bad Linux include is resolved to the provided
`model/model/22nm_MGK.pm` in a generated working copy. Inputs are untouched.
W/L are drawn dimensions: model XL/LINT/WINT alter effective dimensions.
Ldiff=44nm is defined but unused; no explicit diffusion geometry is set here.

Vd/Vs/Vb are zero-volt clamps/probes from drain/source/body to ground. Vg
is a zero-volt probe from gate to Ref, so VG=VRef. Vdd supplies Ref. Gate
power is supplied by Vdd even though I(Vg) measures its current. Vg itself
has zero voltage across it.

The loop increments before `dc TEMP 30 90 60`: no zero-bias measurement.
This build emits .05..1.20V at 30 and 90C, 48 rows. Floating accumulation
determines the last point; do not infer endpoints from `while ... le 1.2`.
An integer-indexed list is better for a future clean sweep. TEMP uses Celsius;
TNOM=27C is reference temperature, not this operating sweep's temperature.
`abs(V(Ref))` affects only printed voltage, not current signs.

**VDS=0 throughout.** A channel can exist with no ordinary drain-source
on-current. Gate tunnelling can inject current into drain/source/body. The
terminal drain current is consequently not a pure subthreshold measurement.
Voltage-source current is positive from its + to - terminal; here current
into each device terminal equals **-I(source)**. The four signed terminal
currents must sum to zero at DC; adding their magnitudes is incorrect.

The path-only copy retains original tolerances; a separate verified copy
uses ABSTOL=1e-20, RELTOL=1e-9, VNTOL=1e-12. Internal body-resistor arithmetic
leaves sub-fA cancellation residue. Acceptance is explicitly 1aA + 0.01%
of summed terminal magnitudes; measured values are in verification.json.

## Mechanisms: what is enabled and what can be measured

* IGCMOD=1 and IGBMOD=1 enable gate/channel and gate/body tunnelling. Saved
  quantities include IGS/IGD, IGCS/IGCD and IGB. PMOS component signs use
  model polarity; do not assume every internal component uses external signs.
* `@m[id]` in this build is a channel-current magnitude, including off-region
  subthreshold conduction, rather than total external drain current. Its
  direction is recovered using sign(VD-VS), including reversed terminals.
* **`@m[isub]` is substrate/impact-ionization current, not subthreshold
  leakage.** This distinction is essential in the viva.
* Nonzero AGIDL/BGIDL/CGIDL configure induced leakage; IGIDL/IGISL are
  exposed. Do not assume a modern GIDLMOD switch in this old card.
* DIOMOD=1 and nonzero junction densities enable junction currents IBD/IBS.
  RBODYMOD=1 and RGATEMOD=1 add internal resistances/nodes; observed TEMPMOD=0.
  Body terminal current can contain junction, gate/body, GIDL and impact
  contributions. No single terminal is assumed to represent one mechanism.
* Capacitive parameters exist but contribute no static displacement current.
  No separate layout parasitics, aging or process variation have been added.

The model warns that TOXE/TOXP/DTOX are specified inconsistently and DTOX is
ignored. NMOS values satisfy TOXE=TOXP+DTOX; PMOS values do not (0.67nm versus
0.40+0.25nm). We retain the warning and the original model. A separate
ablation copy changes only the two tunnelling switches. A zero component at
one bias is not proof the mechanism is disabled everywhere.

References: [official NGSPICE documentation](https://ngspice.sourceforge.io/docs.html),
[device-model manuals](https://ngspice.sourceforge.io/literature.html), the
locally installed version43 manual, and retained `show`/`showmod` output.

## Regression and held-out accuracy

For the four PDF cases, compare a degree-2 polynomial baseline with weighted
local quadratic regression (64 neighbors), using |Vref|, T, W,L. Targets are
`asinh(I/1pA)`: signed, finite at zero, log-like at large magnitudes. Separate
configuration models avoid conflating distinct biases. All 45C rows are
validation; all 105C rows test; others train. All terminals/configurations
at a condition stay together. Validation transformed MAE selects the method;
both models' scores remain visible. There is no random row split.

The circuit model learns from isolated devices at independent drain/source
biases. Its structured regression learns log(channel conductance), asinh
residual drain current after channel subtraction, gate current and body
current on a tensor grid. Channel current is `(VD-VS)*G`, exactly zero at
VD=VS. This avoids fitting a huge on-current plus tiny gate current as one
log target. Source is constrained by `IS=-(ID+IG+IB)`.

Only known type, terminal biases, VDD,T at the stated fixed geometry are
features. Simulator current and gds are **training labels only**, used to
identify channel conductance and its zero-VDS limit. No measured current,
threshold, gm/gds or full-gate simulator voltage is available to prediction.
Whole VDD/T pairs are held out. Interstage gates are rounded to a logic rail,
with deviations recorded. Continuous analog gates, other body bias, geometry,
process cards or extrapolation require additional training.

R2, MAE, RMSE use raw A, not transformed space. Relative error is
`100*abs(pred-ref)/max(abs(ref),1e-12 A)`. Report mean, p95, maximum, ordinary
MAPE for |ref|>=1pA, and fraction below that floor. Below 1pA this is a scaled
absolute error; 1% means <10fA, not ordinary 1% relative accuracy. R2 for a
practically constant target is undefined. No epsilon-based metric is claimed
as proof of uniformly <1% conventional relative error.

## Stack voltages and circuit accounting

Python independently solves every unknown internal/output voltage by KCL
using learned terminal currents, topology, input bits, VDD,T. Bounded damped
Newton iteration stops at <1fA maximum nodal imbalance; failures are flagged.
Full-gate NGSPICE provides reference voltages **after** prediction. Every
static input pattern is simulated and its logic truth table checked.

Supply draw is -I(VSUP), independently verified by a cut over all device
terminals directly wired to VDD. Body/source/drain contributions are included
where connected; series-device currents are not counted twice. VDD*I_supply
is reported separately from total static power, which also includes power
delivered or absorbed by ideal input drivers. Standalone all-on stacks
conduct channel DC current and are not called leakage-only states.

Circuit OP settings: GMIN=1e-20, ABSTOL=1e-18, RELTOL=1e-7, VNTOL=1e-10,
BYPASS=0, ITL1=500. Non-binding `.nodeset` logic guesses aid convergence.
The initially stricter AND2 solve failed; the failure audit records it.
Convergence trials and measured-node isolated replay check consistency.

Diagnostic replay deliberately uses measured node voltages and verifies that
isolated-device currents recombine into complete-gate supply current. Its
excellent agreement is **not independent ML accuracy**. Those diagnostic
columns are separate from independently predicted voltages/currents.

## Failures and next experiment

Delivered tables show passes and failures honestly. R2 can be dominated by
large currents despite substantial relative error at sign changes and
cancellations. Literal PMOS_int also contains forward body-diode conduction.
Inspect magnitude-binned errors and worst cases before making accuracy claims.

To pursue uniform <1%, design new training data from **validation** failures:
denser T/VDD, adaptive near-rail/zero-crossing biases, continuous near-rail
interstage gate samples. Add holdouts across several supplies, temperatures
and geometries. Reserve a fresh final test set; do not repeatedly tune against
the delivered .85V/105C test. More model capacity does not repair missing bias
coverage or wrong current accounting.
