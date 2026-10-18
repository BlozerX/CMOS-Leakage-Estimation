"""Independent KCL solve with learned devices versus complete-circuit NGSPICE."""
from dataclasses import dataclass
import itertools
import json
import pickle
import numpy as np
import pandas as pd
from .spice import MODEL, OUT, ROOT, run, read_wrdata, sha256, write_json, include_path
from .models import scores


@dataclass
class FET:
    name: str
    kind: str
    d: str
    g: str
    s: str
    b: str
    @property
    def nodes(self): return [self.d,self.g,self.s,self.b]
    @property
    def width(self): return 44 if self.kind=='nmos' else 88


def topology(name):
    f=[]
    def n(label,d,g,s): f.append(FET(label,'nmos',d,g,s,'0'))
    def p(label,d,g,s): f.append(FET(label,'pmos',d,g,s,'vdd'))
    def inv(label,out,gate):
        n('n'+label,out,gate,'0'); p('p'+label,out,gate,'vdd')
    if name=='INV':
        inv('o','y','a'); return f,['a'],['y']
    if name in ['NAND2','AND2']:
        out='y' if name=='NAND2' else 'z'
        p('pa',out,'a','vdd'); p('pb',out,'b','vdd')
        n('na',out,'a','x'); n('nb','x','b','0')
        if name=='AND2': inv('o','y','z')
        return f,['a','b'],[out,'x']+(['y'] if name=='AND2' else [])
    if name=='AO31':
        # Y=(A AND B AND C) OR D: AOI31 followed by inverter, matching slide 11.
        for gate in ['a','b','c']: p('p'+gate,'xp',gate,'vdd')
        p('pd','z','d','xp')
        n('na','z','a','x1'); n('nb','x1','b','x2'); n('nc','x2','c','0'); n('nd','z','d','0')
        inv('o','y','z')
        return f,['a','b','c','d'],['z','xp','x1','x2','y']
    if name.startswith('STACK_'):
        kind=name.split('_')[1][0]; count=int(name[-1])
        inputs=list('abc'[:count]); unknowns=[f'x{i}' for i in range(1,count)]
        path=['vdd']+unknowns+['0']
        for j,g in enumerate(inputs):
            if kind=='N': n(f'n{j}',path[j],g,path[j+1])
            else: p(f'p{j}',path[j+1],g,path[j])
        return f,inputs,unknowns
    raise ValueError(name)


def expected(name,bits):
    if name=='INV': return 1-bits[0]
    if name=='NAND2': return int(not all(bits))
    if name=='AND2': return int(all(bits))
    if name=='AO31': return int(all(bits[:3]) or bits[3])
    return None


def initial(name,bits,unknowns,vdd):
    values={u:vdd*.15 for u in unknowns}
    if 'y' in values: values['y']=expected(name,bits)*vdd
    if 'z' in values: values['z']=(1-expected(name,bits))*vdd
    if 'xp' in values: values['xp']=vdd*.9
    if name.startswith('STACK_P'): values={u:vdd*.85 for u in unknowns}
    return np.array([values[u] for u in unknowns])


def direct(name,bits,vdd,temp,split):
    fets,inputs,unknowns=topology(name)
    pattern=''.join(map(str,bits))
    folder=OUT/'circuits/netlists'; folder.mkdir(parents=True,exist_ok=True)
    stem=f'{name}_{pattern}_V{vdd}_T{temp}'
    net=folder/f'{stem}.net'
    lines=[f'* {name} inputs {pattern}; isolated source probes positive INTO FET',
           f'.include "{include_path(MODEL, net)}"',
           '.options gmin=1e-20 abstol=1e-18 reltol=1e-7 vntol=1e-10 bypass=0 itl1=500',f'.temp {temp}',f'VSUP vdd 0 {vdd}']
    lines += [f'VIN_{g} {g} 0 {bit*vdd}' for g,bit in zip(inputs,bits)]
    # Logic-state starting guesses aid DC convergence without clamping nodes.
    lines += ['.nodeset '+ ' '.join(f'v({u})={value:.16g}' for u,value in zip(unknowns,initial(name,bits,unknowns,vdd)))]
    for fet in fets:
        for t,node in zip('dgsb',fet.nodes): lines.append(f'VP_{fet.name}_{t} {node} {fet.name}_{t} 0')
        w=fet.width
        lines.append(f'M{fet.name} {" ".join(fet.name+"_"+t for t in "dgsb")} {fet.kind} W={w}n L=22n AD={w*44}e-18 AS={w*44}e-18 PD={2*(w+44)}n PS={2*(w+44)}n')
    vector=[f'v({u})' for u in unknowns]+['i(VSUP)']+[f'i(VIN_{g})' for g in inputs]
    vector += [f'i(VP_{fet.name}_{t})' for fet in fets for t in 'dgsb']
    lines+=['.control','set numdgt=15','set wr_singlescale','set wr_vecnames','op',
            f'wrdata {stem}.dat {" ".join(vector)}','quit','.endc','.end']
    net.write_text('\n'.join(lines)+'\n')
    run(net)
    row=read_wrdata(folder/f'{stem}.dat')
    assert row.shape==(1,len(vector)+1)
    a=row[0,1:]; size=len(unknowns)
    voltage=dict(zip(unknowns,a[:size]))
    supply=-a[size]
    external=-a[size+1:size+1+len(inputs)]
    currents=a[size+1+len(inputs):].reshape(-1,4)
    supply_cut=sum(currents[i,t] for i,fet in enumerate(fets) for t,node in enumerate(fet.nodes) if node=='vdd')
    if abs(supply_cut-supply)>1e-14: raise AssertionError('Supply cut does not match source current')
    if expected(name,bits) is not None:
        if int(voltage['y']>.5*vdd)!=expected(name,bits): raise AssertionError('Incorrect logic truth table')
    result={'circuit':name,'inputs':pattern,'VDD_V':vdd,'temperature_C':temp,'split':split,
            'reference_supply_A':supply,'reference_supply_power_W':vdd*supply,
            'reference_all_sources_power_W':vdd*supply+sum(bit*vdd*i for bit,i in zip(bits,external)),
            'direct_max_device_KCL_A':float(np.max(abs(currents.sum(axis=1)))),
            'supply_cut_error_A':supply_cut-supply,'netlist':net.relative_to(ROOT).as_posix(),'netlist_sha256':sha256(net)}
    result.update({f'reference_{u}_V':value for u,value in voltage.items()})
    devices=[]
    nodes={'vdd':vdd,'0':0,**dict(zip(inputs,np.array(bits)*vdd)),**voltage}
    for i,fet in enumerate(fets):
        devices.append({'circuit':name,'inputs':pattern,'VDD_V':vdd,'temperature_C':temp,'device':fet.name,'device_type':fet.kind,
            **{f'V{t}_V':nodes[node] for t,node in zip('dgsb',fet.nodes)},
            **{f'I{t}_A':currents[i,j] for j,t in enumerate('dgsb')}})
    return result,devices


def estimate(model,name,bits,vdd,temp):
    fets,inputs,unknowns=topology(name)
    fixed={'vdd':vdd,'0':0,**dict(zip(inputs,np.array(bits)*vdd))}
    def evaluate(x):
        nodes=fixed|dict(zip(unknowns,x))
        current=np.zeros((len(fets),4))
        for kind in ['nmos','pmos']:
            indices=[i for i,f in enumerate(fets) if f.kind==kind]
            if not indices: continue
            volts=np.array([[nodes[n] for n in fets[i].nodes] for i in indices])
            current[indices]=model.predict(kind,*volts.T,temp,vdd)
        r=np.zeros(len(x)); magnitude=np.zeros(len(x))
        for i,fet in enumerate(fets):
            for j,node in enumerate(fet.nodes):
                if node in unknowns:
                    k=unknowns.index(node); r[k]+=current[i,j]; magnitude[k]+=abs(current[i,j])
        return r,current,magnitude,nodes
    x=initial(name,bits,unknowns,vdd)
    converged=False
    for iteration in range(100):
        r,current,mag,nodes=evaluate(x)
        if np.max(abs(r))<1e-15:
            converged=True; break
        jac=np.zeros((len(x),len(x)))
        for j in range(len(x)):
            plus=x.copy(); minus=x.copy()
            plus[j]=min(vdd,x[j]+1e-7); minus[j]=max(0,x[j]-1e-7)
            jac[:,j]=(evaluate(plus)[0]-evaluate(minus)[0])/(plus[j]-minus[j])
        dx=np.linalg.lstsq(jac,-r,rcond=1e-14)[0]
        if np.max(abs(dx))>.2*vdd: dx*=.2*vdd/np.max(abs(dx))
        scales=np.maximum(mag,1e-12)
        merit=np.linalg.norm(r/scales)
        accepted=False
        for factor in [1,.5,.25,.125,.0625,.03125,.015625,.0078125]:
            trial=np.clip(x+factor*dx,0,vdd)
            if np.linalg.norm(evaluate(trial)[0]/scales)<merit:
                x=trial; accepted=True; break
        if not accepted: break
    r,current,mag,nodes=evaluate(x)
    supply=sum(current[i,j] for i,fet in enumerate(fets) for j,node in enumerate(fet.nodes) if node=='vdd')
    power=sum(nodes[node]*current[i,j] for i,fet in enumerate(fets) for j,node in enumerate(fet.nodes))
    gate_rail_error=max(min(abs(nodes[f.g]),abs(vdd-nodes[f.g])) for f in fets)
    result={'estimated_supply_A':supply,'estimated_supply_power_W':vdd*supply,
            'estimated_all_sources_power_W':power,'solver_converged':converged,
            'solver_iterations':iteration+1,'solver_KCL_A':float(np.max(abs(r))),
            'max_gate_rail_approximation_V':gate_rail_error}
    result.update({f'estimated_{u}_V':nodes[u] for u in unknowns})
    return result


def main():
    dataset_metadata=json.loads((OUT/'datasets/metadata.json').read_text())
    if dataset_metadata['model_sha256']!=sha256(MODEL):
        raise RuntimeError('Model card changed since characterization; regenerate the datasets and models.')
    training_metadata=json.loads((OUT/'models/training_metadata.json').read_text())
    if any(sha256(OUT/'datasets'/name)!=digest for name,digest in training_metadata['data_sha256'].items()):
        raise RuntimeError('Dataset changed since model training; retrain before circuit evaluation.')
    with (OUT/'models/device_grid.pkl').open('rb') as f: model=pickle.load(f)
    cases=[]; devices=[]
    # No circuit reference voltages are given to the estimator. Every estimate
    # solves all unknown nodes from known topology, inputs, VDD and temperature.
    conditions=[(.7,30,'train_domain'),(.8,60,'train_domain'),(.9,90,'train_domain'),
                (.75,45,'validation'),(.85,105,'test')]
    simple_passed=False
    for name in ['INV','NAND2','AND2','STACK_N2','STACK_N3','STACK_P2','STACK_P3','AO31']:
        if name=='AO31' and not simple_passed:
            raise RuntimeError('Simple circuit structural/conservation checks must pass before AO31.')
        _,inputs,unknowns=topology(name)
        for vdd,temp,split in conditions:
            for bits in itertools.product([0,1],repeat=len(inputs)):
                ref,detail=direct(name,bits,vdd,temp,split)
                pred=estimate(model,name,bits,vdd,temp)
                ref.update(pred)
                ref['supply_relative_error_pct']=100*abs(pred['estimated_supply_A']-ref['reference_supply_A'])/max(abs(ref['reference_supply_A']),1e-12)
                ref['max_node_error_V']=max(abs(ref[f'reference_{u}_V']-pred[f'estimated_{u}_V']) for u in unknowns)
                cases.append(ref); devices.extend(detail)
        if name=='AND2':
            # Gate truth tables and supply cuts are structural prerequisites;
            # prediction accuracy remains separately reported, including failures.
            simple_passed=all(c['supply_cut_error_A']<1e-14 for c in cases)
        print(f'{name}: all static patterns and five operating conditions complete',flush=True)
    table=pd.DataFrame(cases)
    table.to_csv(OUT/'circuits/comparison.csv',index=False)
    pd.DataFrame(devices).to_csv(OUT/'circuits/direct_device_terminals.csv',index=False)
    metrics=[]
    for (name,split),part in table.groupby(['circuit','split']):
        metrics.append({'circuit':name,'split':split}|scores(part.reference_supply_A.values,part.estimated_supply_A.values)|{
            'max_node_error_V':float(part.max_node_error_V.max()),'converged_cases':int(part.solver_converged.sum()),
            'max_solver_KCL_A':float(part.solver_KCL_A.max())})
    pd.DataFrame(metrics).to_csv(OUT/'evaluation/circuit_metrics.csv',index=False)
    write_json(OUT/'circuits/metadata.json',{
        'case_count':len(cases),'conditions':conditions,'all_logic_truth_tables_passed':True,
        'AO31_function':'Y=(A AND B AND C) OR D; AOI31 plus inverter, per slide 11 circuit.',
        'current_comparison':'Supply source current drawn = -I(VSUP), equal to one cut over all device terminals directly attached to VDD.',
        'power_comparison':'VDD*I_supply separately from sum of power supplied by VDD and ideal input drivers.',
        'estimator':'Independent KCL root solve from learned isolated-device grid; no NGSPICE internal voltages used as features.',
        'approximation':'Interstage gate voltages rounded to nearest rail in device grid. Rail deviation is recorded per case.',
        'geometry':'NMOS 44nm, PMOS 88nm, L22nm, diffusion length44nm; no fanout/external load.',
        'solver_failures':int((~table.solver_converged).sum()),
        'max_node_error_V':float(table.max_node_error_V.max()),
        'AO31_extension_prerequisite':'Simple gate truth tables and supply-current accounting passed; prediction accuracy is not asserted to meet 1%.',
    })
    print(table[table.split=='test'][['circuit','inputs','reference_supply_A','estimated_supply_A','supply_relative_error_pct','max_node_error_V','solver_converged']].to_string(index=False),flush=True)


if __name__=='__main__': main()
