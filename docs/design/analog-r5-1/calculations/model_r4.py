"""R3 electrical model from explicit pin/net contract. SI units throughout.
Ideal opamps and a transparent finite one-pole sensitivity model, NOT a TI
macromodel and NOT measured hardware. Every parasitic is an assumption.
"""
from pathlib import Path
import json
import numpy as np
from scipy.optimize import brentq
ROOT=Path(__file__).resolve().parent
NOMINAL={'R1':510e3,'R2':510e3,'R3':75e3,'R4':82e3,'R5':750.,'R6':750.,'R7':330.,'R8':330.,'R9':330.,'R10':10e6,'R11':4.7e6,'R12':1e3,'R14':1.6e3,'R15':750.,'R16':820.,'R17':10e3,'R18':1e3,'C1':10e-9,'C2':10e-9,'C3':68e-9,'C4':10e-9,'C5':1e-9,'C6':100e-9,'C7':1e-6,'C8':1.8e-9,'C9':1e-6,'C10':100e-12,'C11':100e-12}
PARASITIC_REFERENCE={'Cr1':0.,'Cr2':0.,'Csum':20e-12,'Cr18':0.,'Cdirect':0.,'Cpin':0.,'Cdiff':0.}
MODES=('DC_WIDE','AC_WIDE','AC_SENSITIVE')

class Circuit:
    """MNA matrices: (G+s*C)x = B_G*u+s*B_C*u, u=(CH1,V_A).
    Ideal opamp rows impose Vplus=Vminus, leaving output current unknown.
    Finite model adds an internal voltage E, (1+s*tau)E=A0(Vplus-Vminus),
    followed by output resistance Ro. No slew, saturation or overload recovery.
    """
    def __init__(self,mode='DC_WIDE',values=None,parasitics=None,finite=None,coupling_short=False):
        self.mode=mode; self.values=dict(NOMINAL); self.values.update(values or {})
        self.par=dict(PARASITIC_REFERENCE); self.par.update(parasitics or {})
        c=json.loads((ROOT/'baseline-r2-netlist.json').read_text())
        pin={p:n for n,ps in c['nodes'].items() for p in ps}
        aliases={'ADC_TARGET':'ADC_NODE'}
        if mode.startswith('DC'):
            aliases.update({'CORE_IN':'CH1','AC_NODE':'CH1'})
        else: aliases.update({'CORE_IN':'AC_NODE'})
        if mode.endswith('WIDE'): aliases['FB_D']='DRIVE'
        else: aliases['FB_D']='GAIN_REF'
        if coupling_short: aliases['C9_RIGHT']='CH1'
        def name(n):
            while n in aliases:n=aliases[n]
            return n
        self.name=name
        nodes=sorted({name(n) for n in c['nodes'] if n not in ('AGND','CH1','V_A') and not n.startswith('unconnected')}-{name('CH1'),name('V_A')})
        self.amps=[('A','IN_A','BUF','BUF'),('B','Y1','LP1','LP1'),('C','Y2','LP2','LP2'),('D','BUF','FB_D','DRIVE')]
        # Internal E source requires a second unknown in finite mode.
        extra=[f'I_{a}' for a,*_ in self.amps]+([f'E_{a}' for a,*_ in self.amps] if finite else [])
        self.nodes=nodes+extra;self.idx={n:i for i,n in enumerate(self.nodes)}
        n=len(self.nodes);self.G=np.zeros((n,n));self.C=np.zeros((n,n));self.Bg=np.zeros((n,2));self.Bc=np.zeros((n,2))
        self.external={'CH1':0,'V_A':1};self.finite=finite
        def addrow(M,B,row,node,v):
            node=name(node)
            if node=='AGND':return
            if node in self.external:B[row,self.external[node]]-=v
            else:M[row,self.idx[node]]+=v
        self.addrow=addrow
        def passive(M,B,a,b,v):
            a=name(a);b=name(b)
            for u,w in ((a,b),(b,a)):
                if u in self.idx:
                    row=self.idx[u];addrow(M,B,row,u,v);addrow(M,B,row,w,-v)
        self.passive=passive
        for ref,val in self.values.items():
            a,b=pin[ref+'.1'],pin[ref+'.2']
            if coupling_short and ref=='C9':continue
            if ref.startswith('R'):passive(self.G,self.Bg,a,b,1/val)
            else:passive(self.C,self.Bc,a,b,val)
        for key,a,b in [('Cr1','CORE_IN','IN_MID'),('Cr2','IN_MID','SUM'),('Csum','SUM','AGND'),('Cr18','SUM','IN_A'),('Cdirect','CH1','IN_A'),('Cpin','IN_A','AGND'),('Cdiff','IN_A','BUF')]:
            passive(self.C,self.Bc,a,b,self.par[key])
        for a,p,m,o in self.amps:
            ir=self.idx['I_'+a];oi=self.idx[name(o)]
            self.G[oi,ir]+=1
            if not finite:
                addrow(self.G,self.Bg,ir,p,1);addrow(self.G,self.Bg,ir,m,-1)
            else:
                A0,GBW,Ro=finite;ei=self.idx['E_'+a]
                addrow(self.G,self.Bg,ir,o,1);self.G[ir,ei]-=1;self.G[ir,ir]-=Ro
                self.G[ei,ei]+=1;self.C[ei,ei]+=A0/(2*np.pi*GBW)
                addrow(self.G,self.Bg,ei,p,-A0);addrow(self.G,self.Bg,ei,m,A0)
        # Scale rows independently; currents have physical SI coordinates.
        scale=1/np.maximum(np.maximum(abs(self.G).max(1),abs(self.C).max(1)*1e6),1e-30)
        self.Gs=self.G*scale[:,None];self.Cs=self.C*scale[:,None]
        self.Bgs=self.Bg*scale[:,None];self.Bcs=self.Bc*scale[:,None]

    def solve(self,f,vin=1.,va=0.):
        f=np.asarray(f);s=2j*np.pi*f
        A=self.Gs+s[...,None,None]*self.Cs
        u=np.array([vin,va]);b=self.Bgs@u+s[...,None]*(self.Bcs@u)
        return np.linalg.solve(A,b[...,None])[...,0]
    def node(self,x,n):return x[...,self.idx[self.name(n)]]
    def response(self,f):return self.node(self.solve(f),'ADC_NODE')
    def dc(self,vin=0.,va=3.3):
        x=self.solve(0,vin,va).real
        return {n:float(x[self.idx[self.name(n)]] ) for n in ['SUM','IN_A','BUF','GAIN_REF','DRIVE','LP1','LP2','ADC_NODE']}
    def gain(self):
        ref=Circuit(self.mode,self.values,{k:0. for k in self.par},self.finite,coupling_short=True)
        return float(ref.response(0).real)
    def finite_poles(self):
        """Remove descriptor algebraic states by SVD; no fake huge finite poles."""
        from scipy.linalg import svd,eigvals
        unit=1e-6;U,sv,Vh=svd(self.Cs/unit);rank=int(sum(sv>sv[0]*1e-12))
        g=U.T@self.Gs@Vh.T
        reduced=g[:rank,:rank]-g[:rank,rank:]@np.linalg.solve(g[rank:,rank:],g[rank:,:rank])
        return eigvals(-reduced/sv[:rank,None])/unit

    def cutoff(self):
        g=self.gain()
        return brentq(lambda f:abs(self.response(f))/g-2**-.5,1e3,1e5)


def algebraic_front(f,v=None,p=None,ac=False):
    """Independent two-equation reduction, separate from MNA construction."""
    r=dict(NOMINAL);r.update(v or {});cp=dict(PARASITIC_REFERENCE);cp.update(p or {})
    s=2j*np.pi*np.asarray(f)
    z1=r['R1']/(1+s*r['R1']*cp['Cr1']);z2=r['R2']/(1+s*r['R2']*cp['Cr2'])
    z18=r['R18']/(1+s*r['R18']*cp['Cr18'])
    z0=r['R17']+1/(s*r['C9']) if ac else 0
    zin=z0+z1+z2
    a=1/zin+1/r['R3']+1/r['R4']+s*cp['Csum']+1/z18
    b=-1/z18;d=1/z18+s*(r['C11']+cp['Cpin']+cp['Cdirect'])
    # With ideal A follower, Cdiff carries zero current.
    return (a*s*cp['Cdirect']-b/zin)/(a*d-b*b)


def algebraic_total(f,mode='DC_WIDE',v=None,p=None):
    r=dict(NOMINAL);r.update(v or {});s=2j*np.pi*np.asarray(f)
    h=algebraic_front(f,r,p,mode.startswith('AC'))
    if mode.endswith('SENSITIVE'): h*=1+r['R14']/(1+s*r['R14']*r['C10'])*(1/r['R15']+1/r['R16'])
    for ra,rb,cf,cg in [('R5','R6',r['C1']+r['C8'],'C2'),('R7','R8',r['C3'],'C4')]:
        h/=1+s*r[cg]*(r[ra]+r[rb])+s*s*r[ra]*r[rb]*cf*r[cg]
    return h/(1+s*r['R9']*r['C5'])

if __name__=='__main__':
    for m in MODES:
        c=Circuit(m); f=np.geomspace(.1,1e7,1000)
        err=np.max(np.abs(c.response(f)-algebraic_total(f,m)))
        print(m,c.gain(),c.dc(),c.cutoff(),'identity error',err)
        assert err<1e-10
