"""Serializable graph model. Compatible with Material Lab web version 1."""
import copy
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFINITIONS = json.loads((ROOT / 'definitions.json').read_text(encoding='utf-8-sig'))
DEFS = {d['id']: d for d in DEFINITIONS}
CHANNELS = ('base', 'height', 'rough', 'normal')


def empty():
    return dict(version=1, nodes=[], bindings=dict.fromkeys(CHANNELS))


def validate(g):
    if not isinstance(g, dict) or g.get('version') != 1 or not isinstance(g.get('nodes'), list):
        raise ValueError('不是 Material Lab v1 工程')
    if len(g['nodes']) > 100:
        raise ValueError('目前最多支持 100 个节点')
    nodes = {}
    for n in g['nodes']:
        if not isinstance(n, dict) or type(n.get('id')) is not int or n['id'] in nodes or n.get('type') not in DEFS:
            raise ValueError('节点 ID 或类型无效')
        d = DEFS[n['type']]
        if not all(type(n.get(k)) in (int, float) and math.isfinite(n[k]) for k in ('x', 'y')):
            raise ValueError('节点坐标无效')
        if not isinstance(n.get('inputs'), list) or len(n['inputs']) != len(d['inputs']):
            raise ValueError('输入端口无效')
        if not isinstance(n.get('p'), list) or len(n['p']) != len(d['params']):
            raise ValueError('参数数量无效')
        for v, p in zip(n['p'], d['params']):
            if p.get('color'):
                if not isinstance(v, str) or len(v) != 7 or v[0] != '#' or any(c not in '0123456789abcdefABCDEF' for c in v[1:]):
                    raise ValueError('颜色格式无效')
            elif type(v) not in (int, float) or not math.isfinite(v):
                raise ValueError('数值参数无效')
            elif 'options' in p:
                if int(v) != v or not 0 <= v < len(p['options']):
                    raise ValueError('选项超出范围')
            elif not p['min'] <= v <= p['max']:
                raise ValueError('参数超出范围')
        nodes[n['id']] = n
    for n in nodes.values():
        if any(i is not None and (type(i) is not int or i not in nodes) for i in n['inputs']):
            raise ValueError('连线指向不存在的节点')
    visiting, done = set(), set()
    def visit(i):
        if i in visiting:
            raise ValueError('不能连接成循环图')
        if i in done:
            return
        visiting.add(i)
        for j in nodes[i]['inputs']:
            if j is not None:
                visit(j)
        visiting.remove(i)
        done.add(i)
    for i in nodes:
        visit(i)
    if not isinstance(g.get('bindings'), dict) or any(k not in g['bindings'] or (g['bindings'][k] is not None and (type(g['bindings'][k]) is not int or g['bindings'][k] not in nodes)) for k in CHANNELS):
        raise ValueError('材质通道绑定无效')
    return g


def make_node(node_id, kind, x=0, y=0, params=None):
    d = DEFS[kind]
    return dict(id=node_id, type=kind, x=x, y=y, p=copy.deepcopy(params if params is not None else [p['value'] for p in d['params']]), inputs=[None]*len(d['inputs']))


def preset(name='brick'):
    if name=='histogram':
        return validate(json.loads((ROOT/'example-histogram.json').read_text(encoding='utf-8')))
    g = empty()
    def add(kind, x, y, p=None, inputs=None):
        n = make_node(len(g['nodes'])+1, kind, x, y, p)
        if inputs is not None:
            n['inputs'] = inputs
        g['nodes'].append(n)
        return n['id']
    if name == 'metal':
        a = add('cells', 0, 0, [24, 8])
        b = add('clouds', 0, 225, [6, 5, .6])
        h = add('blur', 240, 25, [2], [a])
        col = add('gradientMap', 480, 0, ['#323d49', '#a7b3b9'], [b])
        strength = 2.5
    else:
        a = add('wood' if name == 'wood' else 'brick', 0, 0, [22, 8, .75] if name == 'wood' else None)
        b = add('clouds', 0, 225, [12, 17, .65])
        h = add('blend', 240, 25, [.35, 1], [a, b, None])
        col = add('gradientMap', 480, 0, ['#301b10', '#ba8846'] if name == 'wood' else ['#25221e', '#ae7951'], [h])
        strength = 1.4 if name == 'wood' else 5
    normal = add('normal', 480, 205, [strength, 0], [h])
    rough = add('levels', 240, 275, [0, 1, 2], [b])
    out = add('output', 720, 0, inputs=[col])
    g['bindings'] = dict(base=out, height=h, rough=rough, normal=normal)
    return validate(g)


class GraphModel:
    def __init__(self, graph=None):
        self.graph = copy.deepcopy(validate(graph or preset()))
        self.undo_stack, self.redo_stack = [], []

    def checkpoint(self):
        self.undo_stack.append(copy.deepcopy(self.graph))
        self.undo_stack = self.undo_stack[-60:]
        self.redo_stack.clear()

    def replace(self, graph, remember=True):
        validate(graph)
        if remember:
            self.checkpoint()
        self.graph = copy.deepcopy(graph)

    def connect(self, source, target, port):
        candidate = copy.deepcopy(self.graph)
        next(n for n in candidate['nodes'] if n['id'] == target)['inputs'][port] = source
        validate(candidate)
        self.replace(candidate)

    def undo(self):
        if not self.undo_stack:
            return False
        self.redo_stack.append(copy.deepcopy(self.graph))
        self.graph = self.undo_stack.pop()
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self.undo_stack.append(copy.deepcopy(self.graph))
        self.graph = self.redo_stack.pop()
        return True

    def remove(self, ids):
        if not ids:
            return
        self.checkpoint()
        self.graph['nodes'] = [n for n in self.graph['nodes'] if n['id'] not in ids]
        for n in self.graph['nodes']:
            n['inputs'] = [None if i in ids else i for i in n['inputs']]
        for k, v in self.graph['bindings'].items():
            if v in ids:
                self.graph['bindings'][k] = None

    def node(self, node_id):
        return next((n for n in self.graph['nodes'] if n['id'] == node_id), None)

    def add(self, kind, x, y):
        if len(self.graph['nodes']) >= 100:
            raise ValueError('节点数量已达到 100')
        self.checkpoint()
        n = make_node(max([n['id'] for n in self.graph['nodes']], default=0)+1, kind, x, y)
        self.graph['nodes'].append(n)
        return n['id']
