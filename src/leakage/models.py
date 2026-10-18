"""NumPy-only regression methods; no optional ML dependencies required."""
import itertools
import numpy as np

FLOOR_A = 1e-12
TERMINALS = ['Id_A', 'Ig_A', 'Is_A', 'Ib_A']


def scores(reference, prediction):
    y, p = np.asarray(reference), np.asarray(prediction)
    e = p-y
    relative = np.abs(e)/np.maximum(np.abs(y), FLOOR_A)*100
    mask = np.abs(y)>=FLOOR_A
    sst = np.sum((y-y.mean())**2)
    return {'R2':float(1-np.sum(e*e)/sst) if sst>1e-40 else None,
            'MAE_A':float(np.mean(np.abs(e))), 'RMSE_A':float(np.sqrt(np.mean(e*e))),
            'floored_mean_relative_pct':float(relative.mean()),
            'floored_p95_relative_pct':float(np.percentile(relative,95)),
            'floored_max_relative_pct':float(relative.max()),
            'MAPE_above_1pA_pct':float(np.mean(np.abs(e[mask]/y[mask]))*100) if mask.any() else None,
            'fraction_reference_below_1pA':float((~mask).mean()),
            'fraction_within_1pct':float((relative<1).mean()), 'n':len(y)}


def powers(dim, degree):
    return np.array([p for p in itertools.product(range(degree+1),repeat=dim) if sum(p)<=degree])


def polynomial_features(x, p):
    return np.prod(np.asarray(x)[:,None,:]**p[None,:,:],axis=2)


class Polynomial:
    def __init__(self,degree=2): self.degree=degree
    def fit(self,x,y):
        self.center=np.mean(x,axis=0)
        self.scale=np.maximum(np.std(x,axis=0),1e-6)
        self.powers=powers(x.shape[1],self.degree)
        a=polynomial_features((x-self.center)/self.scale,self.powers)
        self.coef=np.linalg.lstsq(a,y,rcond=1e-10)[0]
        return self
    def predict(self,x):
        return polynomial_features((x-self.center)/self.scale,self.powers)@self.coef


class LocalQuadratic:
    """Distance-weighted quadratic regression, 64 neighbors, fixed ridge."""
    def fit(self,x,y):
        self.center=np.mean(x,axis=0)
        self.scale=np.maximum(np.std(x,axis=0),1e-6)
        self.x=(x-self.center)/self.scale
        self.y=y
        self.powers=powers(x.shape[1],2)
        return self
    def predict(self,x):
        x=(x-self.center)/self.scale
        output=[]
        k=min(64,len(self.x))
        for start in range(0,len(x),128):
            q=x[start:start+128]
            d2=np.sum((q[:,None,:]-self.x[None,:,:])**2,axis=2)
            nn=np.argpartition(d2,k-1,axis=1)[:,:k]
            z=self.x[nn]-q[:,None,:]
            r2=np.take_along_axis(d2,nn,axis=1)
            bandwidth=np.maximum(np.max(r2,axis=1),1e-6)
            weights=np.exp(-3*r2/bandwidth[:,None])
            a=np.prod(z[:,:,None,:]**self.powers[None,None,:,:],axis=3)
            lhs=np.einsum('bki,bk,bkj->bij',a,weights,a)
            rhs=np.einsum('bki,bk,bko->bio',a,weights,self.y[nn])
            lhs+=np.eye(a.shape[-1])[None,:,:]*1e-8
            coef=np.linalg.solve(lhs,rhs)
            output.append(coef[:,0,:])
        return np.concatenate(output)


class DeviceGrid:
    """Structured regression of channel conductance and terminal leakage.

    Learned from isolated devices only. Each grid point stores log channel
    conductance and asinh residual drain/gate/body currents. Source current is
    reconstructed by KCL. Gate bias is rounded to its nearest logic rail; the
    maximum rounding voltage is audited by the circuit caller.
    """
    def fit(self,df):
        self.tables={}
        self.axes={}
        for kind, group in df.groupby('device_type'):
            group=group.copy()
            polarity=1 if kind=='nmos' else -1
            v=group.VDD_V.values
            d=(group.Vd_V.values if polarity==1 else v-group.Vd_V.values)/v
            s=(group.Vs_V.values if polarity==1 else v-group.Vs_V.values)/v
            g=(group.Vg_V.values if polarity==1 else v-group.Vg_V.values)/v
            coords=np.round(np.column_stack([v,group.temperature_C,d,s,g]),10)
            axes=[np.unique(coords[:,j]) for j in range(5)]
            ix=tuple(np.searchsorted(axis,coords[:,j]) for j,axis in enumerate(axes))
            dv=group.Vd_V.values-group.Vs_V.values
            # BSIM4v5 @id is a magnitude for forward AND reversed terminals.
            ich=np.sign(dv)*group.bsim_id_A.values
            conductance=np.divide(np.abs(ich),np.abs(dv),out=group.bsim_gds_S.values.copy(),where=np.abs(dv)>1e-10)
            target=np.column_stack([np.log(np.maximum(conductance,1e-30)),
                                    np.arcsinh((group.Id_A.values-ich)/FLOOR_A),
                                    np.arcsinh(group.Ig_A.values/FLOOR_A),
                                    np.arcsinh(group.Ib_A.values/FLOOR_A)])
            table=np.full(tuple(len(a) for a in axes)+(4,),np.nan)
            table[ix]=target
            if not np.isfinite(table).all(): raise ValueError('Incomplete training tensor')
            self.axes[kind],self.tables[kind]=axes,table
        return self

    def predict(self,kind,vd,vg,vs,vb,temp,vdd):
        vd,vg,vs,vb,temp,vdd=np.broadcast_arrays(vd,vg,vs,vb,temp,vdd)
        shape=vd.shape
        vd,vg,vs,vb,temp,vdd=[a.ravel() for a in [vd,vg,vs,vb,temp,vdd]]
        p=1 if kind=='nmos' else -1
        d=(vd if p==1 else vdd-vd)/vdd
        s=(vs if p==1 else vdd-vs)/vdd
        g=(vg if p==1 else vdd-vg)/vdd
        if np.any(g < -1e-7) or np.any(g > 1+1e-7):
            raise ValueError('Gate voltage outside characterized rails')
        expected_body=0 if p==1 else vdd
        if np.max(abs(vb-expected_body))>1e-8: raise ValueError('Body outside trained rail convention')
        if np.any(np.minimum(d,s)<-1e-7) or np.any(np.maximum(d,s)>1+1e-7):
            raise ValueError('Terminal voltage outside characterized rails')
        coords=np.column_stack([vdd,temp,np.clip(d,0,1),np.clip(s,0,1),(g>=.5).astype(float)])
        axes=self.axes[kind]
        lower=[]; alpha=[]
        for j,axis in enumerate(axes):
            if np.any(coords[:,j]<axis[0]-1e-7) or np.any(coords[:,j]>axis[-1]+1e-7):
                raise ValueError('Extrapolation rejected')
            lo=np.clip(np.searchsorted(axis,coords[:,j],side='right')-1,0,len(axis)-2)
            lower.append(lo)
            alpha.append((coords[:,j]-axis[lo])/(axis[lo+1]-axis[lo]))
        z=np.zeros((len(vd),4))
        for bits in itertools.product([0,1],repeat=5):
            weight=np.prod([alpha[j] if bit else 1-alpha[j] for j,bit in enumerate(bits)],axis=0)
            z+=weight[:,None]*self.tables[kind][tuple(lower[j]+bit for j,bit in enumerate(bits))]
        ch=(vd-vs)*np.exp(z[:,0])
        residual,gate,body=(FLOOR_A*np.sinh(z[:,1:])).T
        drain=ch+residual
        source=-(drain+gate+body)
        return np.column_stack([drain,gate,source,body]).reshape(shape+(4,))
