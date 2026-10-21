import copy,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_instance_transforms import resolve,localize,LIMIT

def transform(x):return dict(position=dict(x=x,y=0,z=0),rotation=dict(x=0,y=0,z=0,w=1000000),scale=dict(x=1000000,y=1000000,z=1000000),parent_entity_id=0)
class HierarchyTests(unittest.TestCase):
    def test_nested_instances_inverse_and_parent_edit(self):
        local={'parent':transform(3000000),'child':transform(2000000),'leaf':transform(-1000000)};parents={'parent':None,'child':'parent','leaf':'child'};before=copy.deepcopy(local)
        world=resolve(local,parents);self.assertEqual(world['leaf']['position']['x'],4000000);self.assertEqual(localize(world,parents),local);self.assertEqual(local,before)
        local['parent']['position']['x']+=1000000;self.assertEqual(resolve(local,parents)['leaf']['position']['x'],5000000)
    def test_missing_parent_cycle_and_overflow_refuse(self):
        for parents in [{'a':'missing','b':None},{'a':'b','b':'a'},{'a':'a','b':None}]:
            with self.assertRaises(ValueError):resolve({'a':transform(1),'b':transform(2)},parents)
        with self.assertRaises(ValueError):resolve({'a':transform(LIMIT),'b':transform(1)},{'a':None,'b':'a'})
    def test_unsupported_transforms_refuse(self):
        for name,value in [('rotation',dict(x=1,y=0,z=0,w=1000000)),('scale',dict(x=2000000,y=1000000,z=1000000)),('parent_entity_id',42),('position',dict(x=1.0,y=0,z=0))]:
            row=transform(1);row[name]=value
            with self.assertRaises(ValueError):resolve({'a':row},{'a':None})
    def test_thousand_deep_chain_is_iterative_and_order_independent(self):
        local={str(i):transform(1) for i in range(1000)};parents={str(i):str(i-1) if i else None for i in range(1000)}
        world=resolve(local,parents);self.assertEqual(world['999']['position']['x'],1000);self.assertEqual(world,resolve(dict(reversed(list(local.items()))),parents));self.assertEqual(localize(world,parents),local)
if __name__=='__main__':unittest.main()
