"""Post-evaluation diagnosis; does not fit or select any regression model."""
import pickle
import numpy as np
import pandas as pd
from .spice import OUT,ROOT,run,read_wrdata,write_json
from .characterize import header,VECTORS,decode
from .circuits import topology
from .models import TERMINALS


def main():
    table=pd.read_csv(OUT/'circuits/comparison.csv',dtype={'inputs':str})
    terminals=pd.read_csv(OUT/'circuits/direct_device_terminals.csv',dtype={'inputs':str})
    subset=terminals[(terminals.temperature_C==105)&(terminals.VDD_V==.85)&(~terminals.circuit.str.startswith('STACK'))].copy()
    with (OUT/'models/device_grid.pkl').open('rb') as f: grid=pickle.load(f)
    destination=OUT/'circuits/isolated_replay'; destination.mkdir(parents=True,exist_ok=True)
    frames=[]
    for kind,group in subset.groupby('device_type'):
        group=group.copy()
        width=44 if kind=='nmos' else 88
        net=destination/f'{kind}.net'; dat=destination/f'{kind}.dat'
        dat.unlink(missing_ok=True)
        text=header(kind,width,22,'Vd d 0 0\nVg g 0 0\nVs s 0 0\nVb b 0 0',net)
        text+='set temp=105\n'
        for _,r in group.iterrows():
            for terminal in 'dgsb': text+=f'alter V{terminal}={r[f"V{terminal}_V"]:.16g}\n'
            text+=f'op\nwrdata {kind}.dat {" ".join(VECTORS)}\nset appendwrite\n'
        text+='quit\n.endc\n.end\n';net.write_text(text)
        run(net)
        replay=decode(read_wrdata(dat),kind,width,22)
        assert len(replay)==len(group)
        pred=grid.predict(kind,*[group[c].values for c in ['Vd_V','Vg_V','Vs_V','Vb_V','temperature_C','VDD_V']])
        for j,t in enumerate(TERMINALS):
            group[f'isolated_{t}']=replay[t].values
            group[f'model_at_reference_nodes_{t}']=pred[:,j]
        frames.append(group)
    detail=pd.concat(frames,ignore_index=True)
    detail.to_csv(destination/'device_replay.csv',index=False)
    cases=[]
    for (name,pattern),part in detail.groupby(['circuit','inputs']):
        fets,_,_=topology(name)
        replay_supply=0;model_supply=0
        for _,r in part.iterrows():
            fet=next(f for f in fets if f.name==r.device)
            for t,node in zip('dgsb',fet.nodes):
                if node=='vdd':
                    replay_supply+=r[f'isolated_I{t}_A']
                    model_supply+=r[f'model_at_reference_nodes_I{t}_A']
        ref=table[(table.circuit==name)&(table.inputs==pattern)&(table.split=='test')].iloc[0]
        cases.append({'circuit':name,'inputs':pattern,'reference_supply_A':ref.reference_supply_A,
            'isolated_replay_supply_A':replay_supply,'model_at_reference_nodes_supply_A':model_supply,
            'independent_model_supply_A':ref.estimated_supply_A,
            'isolated_replay_relative_error_pct':100*abs(replay_supply-ref.reference_supply_A)/max(abs(ref.reference_supply_A),1e-12),
            'model_at_reference_nodes_relative_error_pct':100*abs(model_supply-ref.reference_supply_A)/max(abs(ref.reference_supply_A),1e-12)})
    cases=pd.DataFrame(cases);cases.to_csv(destination/'supply_diagnosis.csv',index=False)
    # Keep the worst errors with their operating conditions for the viva/report.
    predictions=pd.read_csv(OUT/'evaluation/device_predictions.csv')
    predictions['absolute_error_A']=abs(predictions.prediction_A-predictions.reference_A)
    predictions['floored_relative_error_pct']=100*predictions.absolute_error_A/np.maximum(abs(predictions.reference_A),1e-12)
    predictions[predictions.split=='test'].sort_values('floored_relative_error_pct',ascending=False).head(50).to_csv(OUT/'evaluation/worst_device_errors.csv',index=False)
    # Bin performance by reference magnitude to expose cancellation/zero issues.
    predictions['reference_magnitude_bin']=pd.cut(abs(predictions.reference_A),[0,1e-12,1e-10,1e-8,1e-6,1],include_lowest=True).astype(str)
    binned=predictions[predictions.split=='test'].groupby(['task','reference_magnitude_bin']).agg(
        count=('reference_A','size'),mean_relative_pct=('floored_relative_error_pct','mean'),
        max_relative_pct=('floored_relative_error_pct','max'),MAE_A=('absolute_error_A','mean'))
    binned.to_csv(OUT/'evaluation/error_by_magnitude.csv')
    errors=np.column_stack([detail[f'isolated_{t}']-detail[t] for t in TERMINALS])
    write_json(OUT/'evaluation/diagnosis.json',{
        'purpose':'Measured-node isolated replay is a diagnostic consistency check, never a predictive feature or reported independent estimate.',
        'max_isolated_replay_terminal_difference_A':float(abs(errors).max()),
        'max_isolated_replay_supply_relative_error_pct':float(cases.isolated_replay_relative_error_pct.max()),
        'mean_model_reference_node_supply_error_pct':float(cases.model_at_reference_nodes_relative_error_pct.mean()),
        'mean_independent_supply_error_pct':float(table[(table.split=='test')&(~table.circuit.str.startswith('STACK'))].supply_relative_error_pct.mean()),
        'findings':[
            'High R2 is dominated by large currents and does not imply uniformly low relative error.',
            'Relative errors concentrate near cancellations/zero crossings and where log/asinh targets vary rapidly.',
            'Structured interpolation leaves temperature/supply interpolation error; interstage rail rounding adds circuit error.',
            'Literal PMOS_int on PDF page3 forward-biases the source/well junction when Vref is negative; it is not conventional PMOS off-state leakage.',
            'No test-set-driven hyperparameter changes were made; improving <1% uniformly requires a new training/validation design and a fresh test set.'
        ]})
    print(cases.groupby('circuit')[['isolated_replay_relative_error_pct','model_at_reference_nodes_relative_error_pct']].max().to_string(),flush=True)


if __name__=='__main__': main()
