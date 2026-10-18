# Requirements from all 16 visually inspected pages

Primary source: `Project-1_leakage_estimation_annotated.pdf`. Fresh renders are
`generated/pdf_pages/page-01.png` through `page-16.png` at 105 dpi. Every page
was visually read, including handwriting; pre-existing tmp images were not
used as proof of the current PDF's contents.

| Page | Visible content and interpretation |
|---|---|
| 1 | Four-terminal static FET abstraction. Terminal currents point into device. Pairwise mechanisms are not a prescription to sum current magnitudes for supply current. |
| 2 | Single NMOS characterization with VDS, VGS, VBS, PMOS complementary configuration. Supports independent terminal biases. |
| 3 | NMOS_cond: D=S=B=0,G=Vref. NMOS_int: D=Vref,G=S=B=0. PMOS_cond: D=S=B=Vref,G=0. PMOS_int: S=G=0,D=B=Vref with negative Vdd reference. Bottom labels partly cropped; biases legible. |
| 4 | Sample database with PVT, W/L, terminal voltages and currents. Handwriting: develop an ML model, R2 > 0.99, Error% < 1% compared with simulation. Temperature note -40 C to 125 C. Small nominal-voltage/margin note is ambiguous and not a mandatory technology specification. Fin/process sample columns are not all present in this supplied bulk BSIM card. |
| 5 | Two-device stacks and parallel-branch examples. Red dots/INV mark intermediate voltages; one internal node in a simple two-device chain. |
| 6 | Three-device stacks/parallel branches, two internal nodes. Examples, not an explicit checklist of all required networks. |
| 7 | INV_Package: example intermediate-voltage matrices indexed by patterns/supply/temperature. Handwritten SD1/SD2 identify intermediate nodes, not inverters. Values are examples, not reference data for this model. |
| 8 | NOR2/NAND2 example networks with circled PMOS/NMOS stacks. |
| 9 | Multiple stacks with input inverters and several intermediate nodes. |
| 10 | Complex example with reusable stack types and output inverters. |
| 11 | Example Cell AO31. Identifies stacks/nodes for ABCD=0000. Actual circuit is AOI31 plus inverter: Y=(A AND B AND C) OR D. Pull-up conduction labels use complementary PMOS logic. |
| 12 | AO31 subthreshold paths for 0000 and hand sketches of off NMOS/on PMOS chains. |
| 13 | Gate leakage arrows for the same AO31 pattern. |
| 14 | Body leakage arrows and handwritten terminal-voltage sketch. |
| 15 | Example AND2 leakage equations, marked Example, not compulsory. Wmin/2Wmin and process/temperature/INV notes are illustrative, not universal current-accounting equations. |
| 16 | Handwritten NAND2 feeding NOR2, transistor sketches, for all i/p patterns, and NOT/NAND2/NAND3 pattern examples. Supports exhaustive static patterns without mandating every illustrated gate. |

## Scope and material ambiguities

The numerical targets are explicit handwritten aspirations. Their population
(which currents/gates/operating conditions) and definition of Error% are not
specified. We report held-out R2, MAE, RMSE, mean/p95/max floored relative error,
ordinary MAPE above 1pA, and near-zero population. R2 alone is not a pass.

Only supplied 22nm_MGK is selected. Other 22/32/45nm bulk/HP/LP/MGK cards are
alternatives, not a written mandate to run all ten. No statistical process
distribution is provided. Deterministic geometry variation is not process
variation. The many parallel-branch stacks on pages 5-6 are not all enumerated.

Literal PMOS_int is materially different from a conventional PMOS off test:
negative Vref places its source p diffusion above the n-well, forward biasing
the source/body diode. The diagram is reproduced for traceability; its currents
are not described as pure off leakage. General PMOS circuit modelling keeps
the body at positive VDD. Instructor clarification would be useful before
presenting PMOS_int as an intended cutoff measurement; it does not block work.

The user requested inverter -> NAND2 -> AND2 (NAND2 plus inverter). AO31 is
an extension after simple-gate truth-table/accounting checks passed. This is
not a claim that simpler predictive accuracy passed: some AND2 errors exceed 1%.

## Chosen ranges, not additional assignment mandates

* Four cases: |Vref|=0..1V, 25mV step; T=-40,-20,0,20,30,45,60,75,90,105,125C;
  W44/88/132nm; L22/26/30nm. Original 22x22nm remains the milestone device.
* General model training: VDD=.7,.8,.9V; T=-40,0,30,60,90,125C. Validation
  .75V/45C; test .85V/105C. VD spans rails in VDD/40 steps, VS uses 16
  rail-clustered fractions, gate at either rail, body at its CMOS rail.
* General geometry: NMOS W44nm, PMOS W88nm, L22nm, diffusion length44nm.
  AD=AS=W*44nm, PD=PS=2*(W+44nm). Schematic geometry, not extracted layout.
  Original unused Ldiff does not set instance AD/AS/PD/PS implicitly.
* Original 1.2V sweep is reproduced but outside the .7-.9V circuit model.
  A successful simulation is not a foundry reliability specification. Surrogate
  extrapolation is rejected. Ranges cover the sample scale, temperature note,
  and modest geometry variations without assuming additional process nodes.
