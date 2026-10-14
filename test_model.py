import copy
import json
import unittest
from model import GraphModel,DEFINITIONS,validate,preset,empty,make_node,ROOT


class GraphTests(unittest.TestCase):
    def test_all_node_definitions(self):
        for d in DEFINITIONS:
            graph=empty()
            graph['nodes']=[make_node(1,d['id'])]
            validate(graph)

    def test_presets(self):
        for name in ('brick','wood','metal','histogram'):
            g=preset(name)
            self.assertEqual(len(g['nodes']),11 if name=='histogram' else 7)
            self.assertEqual(validate(json.loads(json.dumps(g))),g)

    def test_cycle_is_atomic(self):
        model=GraphModel()
        before=copy.deepcopy(model.graph)
        with self.assertRaisesRegex(ValueError,'循环'):
            model.connect(3,3,0)
        self.assertEqual(before,model.graph)
        self.assertEqual(model.undo_stack,[])

    def test_delete_disconnects_and_undo_restores(self):
        model=GraphModel()
        before=copy.deepcopy(model.graph)
        model.remove({3})
        validate(model.graph)
        self.assertIsNone(model.graph['bindings']['height'])
        self.assertFalse(any(3 in n['inputs'] for n in model.graph['nodes']))
        self.assertTrue(model.undo())
        self.assertEqual(model.graph,before)
        self.assertTrue(model.redo())
        self.assertIsNone(model.node(3))

    def test_bad_parameters(self):
        g=preset()
        g['nodes'][0]['p'][0]=float('nan')
        with self.assertRaises(ValueError):
            validate(g)
        g=preset()
        g['nodes'][3]['p'][0]='#xxxxxx'
        with self.assertRaises(ValueError):
            validate(g)

    def test_web_roundtrip(self):
        file=ROOT.parent/'MaterialLab/example-wood.json'
        if file.exists():
            g=validate(json.loads(file.read_text(encoding='utf-8-sig')))
            self.assertEqual(validate(json.loads(json.dumps(g))),g)


if __name__=='__main__':
    unittest.main()
