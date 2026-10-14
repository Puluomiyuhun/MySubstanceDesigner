"""Restricted numeric interpreter of extracted SBS DAGs, for test reference only.
No arbitrary code loading. Atomic Levels uses the explicitly documented local convention.
"""
import json
from pathlib import Path
import numpy as np
REFERENCE_FILE=Path(__file__).parent/'sbs-node-reference.json'
REFERENCES=json.loads(REFERENCE_FILE.read_text(encoding='utf-8')) if REFERENCE_FILE.exists() else {}
def levels(x,low=0.,high=1.,gamma=1.,outlow=0.,outhigh=1.):
    t=(x>=low).astype(float) if abs(high-low)<1e-7 else np.clip((x-low)/(high-low),0,1)
    return np.clip(outlow+(outhigh-outlow)*np.power(t,1/max(gamma,.00001)),0,1)

def dynamic(param,env,sample):
    if 'constant' in param:return float(param['constant'])
    def evaluate(uid):
        node=param['nodes'][uid];op=node['op'];args=node['args'];value=node['value']
        def arg(key):return evaluate(args[key])
        if op.startswith('const_'):return float((value or '0').split()[0])
        if op.startswith('get_'):return env.get(value,0.)
        if op=='samplelum':return sample
        if op=='set':env[value]=arg('value');return env[value]
        if op=='sequence':arg('seqin');return arg('seqlast')
        if op=='ifelse':return arg('ifpath') if arg('condition') else arg('elsepath')
        a,b=arg('a'),arg('b')
        if op=='add':return a+b
        if op=='sub':return a-b
        if op=='mul':return a*b
        if op=='div':return a/b
        if op=='min':return np.minimum(a,b)
        if op=='max':return np.maximum(a,b)
        if op=='mod':return np.mod(a,b)
        if op=='lreq':return a<=b
        if op=='lerp':return a+(b-a)*arg('x')
        raise ValueError('Unsupported reference function '+op)
    return evaluate(param['root'])

def render_reference(name,parameters,input_image):
    if name not in REFERENCES:raise ValueError('Optional local SBS reference fixture is missing: '+str(REFERENCE_FILE))
    reference=REFERENCES[name];nodes={n['uid']:n for n in reference['nodes']};cache={}
    env={p['id']:float(p['default']) for p in reference['parameters'] if not p['input']};env.update(parameters)
    def visit(uid):
        if uid in cache:return cache[uid]
        n=nodes[uid];inputs={k:visit(v) for k,v in n['connections'].items()};params=n['params']
        if n['kind']=='compInputBridge':output=input_image
        elif n['kind']=='compOutputBridge':output=inputs['inputNodeOutput']
        elif n['filter']=='levels':
            x=inputs['input1'];values={k:dynamic(v,env,x) for k,v in params.items()}
            output=levels(x,values.get('levelinlow',0.),values.get('levelinhigh',1.),1.,values.get('leveloutlow',0.),values.get('levelouthigh',1.))
        elif n['filter']=='pixelprocessor':
            x=inputs['input'];local=dict(env)
            if 'outputsize' in params:dynamic(params['outputsize'],local,x)
            output=np.clip(dynamic(params['perpixel'],local,x),0,1)
        elif n['filter']=='blend':
            output=inputs['destination']+(inputs['source']-inputs['destination'])*inputs['opacity']
        else:raise ValueError('Unsupported atomic node '+str(n['filter']))
        cache[uid]=output;return output
    uid=next(n['uid'] for n in nodes.values() if n['kind']=='compOutputBridge')
    return visit(uid)


