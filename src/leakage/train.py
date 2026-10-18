import json
import pickle
import numpy as np
import pandas as pd
from .spice import OUT, write_json, sha256
from .models import Polynomial, LocalQuadratic, DeviceGrid, scores, TERMINALS, FLOOR_A


def add_metrics(records,task,model,split,y,p):
    for j,t in enumerate(TERMINALS):
        records.append({'task':task,'model':model,'split':split,'terminal':t}|scores(y[:,j],p[:,j]))


def main():
    (OUT/'models').mkdir(parents=True,exist_ok=True)
    (OUT/'evaluation').mkdir(parents=True,exist_ok=True)
    metrics=[]; predictions=[]; selected={}; saved={}
    four=pd.read_csv(OUT/'datasets/pdf_configurations.csv')
    four['split']=np.where(four.temperature_C==105,'test',np.where(four.temperature_C==45,'validation','train'))
    features=['bias_magnitude_V','temperature_C','W_nm','L_nm']
    for config,df in four.groupby('configuration'):
        train=df[df.split=='train']
        x=train[features].values; y=np.arcsinh(train[TERMINALS].values/FLOOR_A)
        candidates={'polynomial_degree_2':Polynomial(2),'local_quadratic_64':LocalQuadratic()}
        selection={}
        for name,model in candidates.items():
            model.fit(x,y)
            val=df[df.split=='validation']
            pred=model.predict(val[features].values)
            selection[name]=float(np.mean(np.abs(pred-np.arcsinh(val[TERMINALS].values/FLOOR_A))))
        winner=min(selection,key=selection.get)
        selected[config]={'selected_by_validation_asinh_MAE':winner,'validation_losses':selection}
        saved[config]=candidates[winner]
        for name,model in candidates.items():
            for split in ['validation','test']:
                part=df[df.split==split]
                pred=FLOOR_A*np.sinh(np.clip(model.predict(part[features].values),-50,50))
                add_metrics(metrics,config,name,split,part[TERMINALS].values,pred)
                if name==winner:
                    for j,t in enumerate(TERMINALS):
                        predictions.append(pd.DataFrame({'task':config,'split':split,'terminal':t,
                            'reference_A':part[t].values,'prediction_A':pred[:,j]}))
        print(f'{config}: selected {winner}',flush=True)
    with (OUT/'models/pdf_config_models.pkl').open('wb') as f: pickle.dump(saved,f)

    general=pd.read_csv(OUT/'datasets/general_devices.csv')
    training=general[general.split=='train']
    grid=DeviceGrid().fit(training)
    with (OUT/'models/device_grid.pkl').open('wb') as f: pickle.dump(grid,f)
    # Simple global baseline uses only known terminal biases, supply, and temperature.
    gf=['Vd_V','Vg_V','Vs_V','VDD_V','temperature_C']
    for kind,df in general.groupby('device_type'):
        tr=df[df.split=='train']
        baseline=Polynomial(2).fit(tr[gf].values,np.arcsinh(tr[TERMINALS].values/FLOOR_A))
        for split in ['validation','test']:
            part=df[df.split==split]
            pred=grid.predict(kind,*[part[c].values for c in ['Vd_V','Vg_V','Vs_V','Vb_V','temperature_C','VDD_V']])
            base=FLOOR_A*np.sinh(np.clip(baseline.predict(part[gf].values),-50,50))
            add_metrics(metrics,'general_'+kind,'structured_device_grid',split,part[TERMINALS].values,pred)
            add_metrics(metrics,'general_'+kind,'polynomial_degree_2',split,part[TERMINALS].values,base)
            for j,t in enumerate(TERMINALS):
                predictions.append(pd.DataFrame({'task':'general_'+kind,'split':split,'terminal':t,
                                                'reference_A':part[t].values,'prediction_A':pred[:,j]}))
    table=pd.DataFrame(metrics)
    table.to_csv(OUT/'evaluation/device_metrics.csv',index=False)
    pd.concat(predictions,ignore_index=True).to_csv(OUT/'evaluation/device_predictions.csv',index=False)
    write_json(OUT/'models/training_metadata.json',{
        'seed':20261018,'dependencies':'NumPy regressions; no optional libraries required',
        'pdf_features':features,'pdf_selection':selected,
        'pdf_split':'All 105 C rows test, all 45 C rows validation, other temperatures training. Every terminal and bias config at a condition stays together.',
        'general_model':'Structured multilinear regression of log conductance and asinh leakage residuals; source constrained by KCL.',
        'general_features':['device_type','Vd_V','Vg_V','Vs_V','Vb_V','VDD_V','temperature_C'],
        'general_geometry':'Fixed L=22nm, NMOS W=44nm, PMOS W=88nm; other geometry rejected by caller.',
        'general_selection':'Structured surrogate specified from physics before viewing test; quadratic baseline for comparison.',
        'target_scale_A':FLOOR_A,'relative_error':'100*abs(pred-reference)/max(abs(reference),1e-12 A); also report ordinary MAPE on references >=1pA.',
        'target_interpretation':'R2 > .99 and error <1%; report mean, p95, max. No single undefined accuracy claim.',
        'data_sha256':{name:sha256(OUT/'datasets'/name) for name in ['pdf_configurations.csv','general_devices.csv']},
        'no_test_tuning':True,
    })
    print(table[(table.split=='test')&(table.terminal=='Id_A')][['task','model','R2','floored_mean_relative_pct','floored_max_relative_pct']].to_string(index=False),flush=True)


if __name__=='__main__': main()
