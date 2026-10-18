"""Integration checks against generated simulation artifacts."""
import json
from pathlib import Path
import pickle
import re
import tarfile
import unittest
import numpy as np
import pandas as pd
from leakage.spice import ROOT,OUT,MODEL,sha256
from leakage.circuits import topology,expected


class WorkflowChecks(unittest.TestCase):
    def test_supplied_files_preserved_and_archive_matches_models(self):
        metadata=json.loads((OUT/'milestone/verification.json').read_text())
        self.assertEqual(sha256(MODEL),metadata['model_sha256'])
        self.assertEqual(sha256(ROOT/'22n_NMOS_ON.net'),metadata['supplied_netlist_sha256'])
        self.assertEqual(sha256(ROOT/'Project-1_leakage_estimation_annotated.pdf'),metadata['pdf_sha256'])
        with tarfile.open(ROOT/'model.tar') as archive:
            for member in archive.getmembers():
                if member.isfile():
                    self.assertEqual(archive.extractfile(member).read(),(ROOT/'model'/member.name).read_bytes())

    def test_device_terminal_biases_and_conservation(self):
        data=pd.read_csv(OUT/'datasets/pdf_configurations.csv')
        self.assertEqual(len(data),16236)
        self.assertEqual(set(data.configuration),{'NMOS_cond','NMOS_int','PMOS_cond','PMOS_int'})
        for config,part in data.groupby('configuration'):
            v=part.bias_magnitude_V.values; z=np.zeros(len(part))
            biases={'NMOS_cond':[z,v,z,z], 'NMOS_int':[v,z,z,z],
                    'PMOS_cond':[v,z,v,v], 'PMOS_int':[-v,z,z,-v]}[config]
            np.testing.assert_allclose(part[['Vd_V','Vg_V','Vs_V','Vb_V']].values,np.array(biases).T,atol=1e-12)
        self.assertLess(data.KCL_residual_A.abs().max(),1e-14)

    def test_no_operating_condition_crosses_general_split(self):
        df=pd.read_csv(OUT/'datasets/general_devices.csv')
        self.assertEqual(len(df),52480)
        self.assertTrue((df.groupby(['VDD_V','temperature_C']).split.nunique()==1).all())
        features=['device_type','W_nm','L_nm','Vd_V','Vg_V','Vs_V','Vb_V','temperature_C','VDD_V']
        self.assertFalse(df.duplicated(features).any())
        self.assertEqual(set(df[df.split=='test'].VDD_V),{.85})
        self.assertEqual(set(df[df.split=='test'].temperature_C),{105})

    def test_stack_polarity_and_all_logic_patterns(self):
        for kind in ['N','P']:
            for count in [2,3]:
                devices,inputs,nodes=topology(f'STACK_{kind}{count}')
                self.assertEqual({d.kind for d in devices},{'nmos' if kind=='N' else 'pmos'})
                self.assertEqual(len(nodes),count-1)
        cases=pd.read_csv(OUT/'circuits/comparison.csv',dtype={'inputs':str})
        self.assertEqual(len(cases),250)
        self.assertTrue(cases.solver_converged.all())
        self.assertLess(cases.solver_KCL_A.max(),1e-15)
        for name in ['INV','NAND2','AND2','AO31']:
            _,inputs,_=topology(name)
            for _,part in cases[cases.circuit==name].groupby(['VDD_V','temperature_C']):
                self.assertEqual(len(part),2**len(inputs))
                for _,case in part.iterrows():
                    self.assertEqual(int(case.reference_y_V>.5*case.VDD_V),expected(name,list(map(int,case.inputs))))
        self.assertLess(cases.supply_cut_error_A.abs().max(),1e-14)

    def test_learned_model_charge_conservation_and_domain_guard(self):
        with (OUT/'models/device_grid.pkl').open('rb') as f: model=pickle.load(f)
        for kind,body in [('nmos',0),('pmos',.85)]:
            currents=model.predict(kind,np.array([0,.85,.3]),np.array([0,.85,.85]),np.array([0,.1,.2]),body,105,.85)
            np.testing.assert_allclose(currents.sum(axis=1),0,atol=1e-18)
        with self.assertRaises(ValueError): model.predict('nmos',.5,0,0,0,30,1.2)
        with self.assertRaises(ValueError): model.predict('nmos',.5,0,0,.1,30,.8)
        with self.assertRaises(ValueError): model.predict('nmos',.5,1.2,0,0,30,.8)

    def test_isolated_replay_validates_supply_accounting(self):
        diagnosis=json.loads((OUT/'evaluation/diagnosis.json').read_text())
        self.assertLess(diagnosis['max_isolated_replay_supply_relative_error_pct'],1e-5)
        self.assertLess(diagnosis['max_isolated_replay_terminal_difference_A'],1e-13)

    def test_total_terminal_power_matches_all_external_sources(self):
        devices=pd.read_csv(OUT/'circuits/direct_device_terminals.csv',dtype={'inputs':str})
        devices['terminal_power_W']=sum(devices[f'V{t}_V']*devices[f'I{t}_A'] for t in 'dgsb')
        keys=['circuit','inputs','VDD_V','temperature_C']
        power=devices.groupby(keys).terminal_power_W.sum()
        cases=pd.read_csv(OUT/'circuits/comparison.csv',dtype={'inputs':str}).set_index(keys)
        difference=power-cases.reference_all_sources_power_W
        # Match the simulator's finite numerical accuracy, rather than demand
        # exact arithmetic from terminal probes in the BSIM internal network.
        reference=cases.reference_all_sources_power_W.reindex(difference.index)
        self.assertTrue((difference.abs() < 1e-18 + 1e-6*reference.abs()).all())

    def test_generated_netlists_use_existing_relative_model_includes(self):
        for netlist in (OUT).rglob('*.net'):
            for include in re.findall(r'^\s*\.include\s+"([^"]+)"',netlist.read_text(),re.I|re.M):
                self.assertFalse(Path(include).is_absolute(),str(netlist))
                self.assertTrue((netlist.parent/include).is_file(),str(netlist))


if __name__=='__main__': unittest.main(verbosity=2)
