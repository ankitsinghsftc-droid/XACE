import copy
import importlib
import json
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/"packages"),str(ROOT/"packages/project-system")]
from native_adoption import plan_adoption, verify_plan, compile_execution_preview, actor_id, digest, encode, AdoptionPlan
from native_adoption import _gde, factory
from authoring_identity import canonical
from tools.world_extensibility_proof import semantic_fixture, rehash


def oid(n): return f"{n:032x}"


def inputs(engine="unity"):
    reader=importlib.import_module(engine+"_authoring")
    doc={"unity":"Assets/World.unity","godot":"res://World.tscn","unreal":"/Game/World"}[engine]
    rows={}
    for n,kind in [(1,"scene"),(2,"object"),(3,"object")]:
        fields={} if n==1 else {"native.name":"Health Boss Player", "transform.position":dict(x="1",y="2",z="3"),"transform.rotation":dict(x="0",y="0",z="0",w="1"),"transform.scale":dict(x="1",y="1",z="1")}
        rows[oid(n)]=dict(metadata=dict(schema="xace.native_identity.v1",namespace_id=oid(100),authoring_id=oid(n),kind=kind,generation="1"),locator=dict(engine=engine,document_id="doc",object_id="native"+str(n)),scene_id=None if n==1 else oid(1),prefab_id=None,parent_id=None,fields=fields,dependencies=[],opaque=[],name="Health Boss Player",path_hint=doc)
    inventory=dict(schema="xace."+engine+"_authoring_inventory.v1",namespace_id=oid(100),objects=rows,source=dict(engine=engine,engine_version=reader.ENGINE_VERSION,reader_version=reader.READER_VERSION,materializer_version=reader.WRITER_VERSION,play_mode=False,documents=[dict(id="doc",before="a"*64,after="a"*64,dirty=False)]))
    data=canonical(inventory);mapping=reader.prepare_identity_map(data,project_id="adoption",branch_id=oid(200))
    cgs=semantic_fixture();cgs["modes"][0]["actors"]=[];cgs["modes"][0]["world"].pop("contract");rehash(cgs)
    selection=[oid(2),oid(3)];choices=choices_for(selection)
    return data,mapping,cgs,selection,choices


def choices_for(selection):
    contract=dict(contract_version=3,id="project.imported",version="1.0.0",schemas=[dict(id="project.imported.v1",definition=dict(type="object",fields={}))],capability_declarations=[],geometry_profiles=[],objects=[])
    role=dict(actor_type="WORLD_OBJECT",control_type="NONE",components=[],semantic_type="project.imported.v1",properties={},capabilities=[],geometry_profile=None,asset_role=None,playback=None)
    return dict(mode_id="reference",new_mode=None,world_contract=contract,objects={k:copy.deepcopy(role) for k in selection},packages=[],legacy_dispositions=[])


def plan(data,mapping,cgs,selection,choices,**kw):
    import hashlib
    return plan_adoption(data,mapping,cgs,selection=selection,choices=choices,expected_source_digest=hashlib.sha256(data).hexdigest(),expected_cgs_digest=digest(cgs),trusted_project=True,**kw)


class NativeAdoptionTests(unittest.TestCase):
    def test_real_native_unknown_behaviors_remain_blocked_after_review(self):
        import hashlib
        folder=Path(__file__).parent/'fixtures/nec007'
        provenance=json.loads((folder/'provenance.json').read_text())
        for engine in ['unity','godot','unreal']:
            data=(folder/(engine+'-unknown.json')).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),provenance[engine+'-unknown']['sha256'])
            reader=importlib.import_module(engine+'_authoring')
            mapping=reader.prepare_identity_map(data,project_id='unknown',branch_id=oid(200))
            value=json.loads(data)
            selected=sorted(k for k,v in value['objects'].items() if any(o['critical'] for o in v['opaque']))
            self.assertTrue(selected)
            choices=choices_for(selected)
            for key in selected:
                if 'presentation.asset' in value['objects'][key]['fields']:choices['objects'][key]['asset_role']='project.visual.v1'
                for opaque in value['objects'][key]['opaque']:
                    choices['legacy_dispositions'].append(dict(object_id=key,opaque_id=opaque['id'],sha256=opaque['sha256'],action='disable_before_play'))
            cgs=inputs()[2];before=encode([cgs,mapping.to_dict(),choices])
            result=plan(data,mapping,cgs,selected,choices).to_dict()
            self.assertFalse(result['candidate_valid']);self.assertFalse(result['play_eligible'])
            self.assertTrue(any(r['severity']=='blocking' for r in result['losses']))
            self.assertTrue(all(not r['executable'] for r in result['legacy_disablement_plan']))
            self.assertEqual(before,encode([cgs,mapping.to_dict(),choices]))

    def test_package_component_defaults_are_explicit_and_repeatable(self):
        data,mapping,cgs,selection,choices=inputs()
        catalog,operation=damage_package(mapping,selection)
        package=catalog.resolve(operation['package_id'],operation['package_hash'])
        package['systems']=[];package['requirements']=dict(component_type_ids=[],system_ids=[],capability_ids=[])
        package['component_schemas']=[dict(type_id=10001,name='PROJECT_CHARGE',source='gcl',defaults=dict(charge=7))]
        package['configurations']=[dict(id='default',defaults={'10001':dict(charge=11)})]
        catalog=type(catalog)([package]);operation['package_hash']=catalog.descriptors()[0]['package_hash'];choices['packages']=[operation]
        first=plan(data,mapping,cgs,selection,choices,gameplay_catalog=catalog).to_dict()
        self.assertTrue(first['candidate_valid'],first['losses'])
        for actor in first['proposed_cgs']['modes'][0]['actors']:self.assertEqual(actor['components'][-1]['defaults'],dict(charge=11))
        self.assertTrue(plan(data,mapping,first['proposed_cgs'],selection,choices,gameplay_catalog=catalog).to_dict()['noop'])
        changed=copy.deepcopy(first['proposed_cgs']);changed['modes'][0]['actors'][0]['components'][-1]['defaults']['charge']=12;rehash(changed)
        self.assertFalse(plan(data,mapping,changed,selection,choices,gameplay_catalog=catalog).to_dict()['candidate_valid'])

    def test_three_axes_no_inference_and_factory(self):
        expected={"unity":dict(x=1000000,y=2000000,z=-3000000),"godot":dict(x=1000000,y=2000000,z=3000000),"unreal":dict(x=20000,y=30000,z=-10000)}
        for engine in expected:
            args=inputs(engine);before=encode([args[2],args[1].to_dict(),args[4]])
            result=plan(*args);report=result.to_dict();self.assertTrue(report["candidate_valid"],report["losses"])
            actor=report["proposed_cgs"]["modes"][0]["actors"][0]
            self.assertEqual(actor["components"],[dict(type_id=1,name="COMP_TRANSFORM_V1",defaults=dict(position=expected[engine],rotation=dict(x=0,y=0,z=0,w=1000000),scale=dict(x=1000000,y=1000000,z=1000000),parent_entity_id=0))])
            self.assertEqual(before,encode([args[2],args[1].to_dict(),args[4]]));self.assertFalse(report["play_eligible"]);self.assertFalse(report["can_commit"])
            self.assertEqual(report["dependency_closure"],[oid(1),oid(2),oid(3)])
            self.assertEqual(result,plan(*args))

    def test_repeat_is_noop_and_existing_edit_is_conflict(self):
        data,mapping,cgs,selection,choices=inputs();first=plan(data,mapping,cgs,selection,choices).to_dict()
        second=plan(data,mapping,first["proposed_cgs"],selection,choices).to_dict()
        self.assertTrue(second["noop"]);self.assertEqual(first["proposed_cgs"],second["proposed_cgs"])
        changed=copy.deepcopy(first["proposed_cgs"]);changed["modes"][0]["actors"][0]["components"][0]["defaults"]["position"]["x"]+=1;rehash(changed)
        with self.assertRaisesRegex(ValueError,"reconciliation"):plan(data,mapping,changed,selection,choices)

    def test_stale_and_untrusted_refused(self):
        import hashlib
        data,mapping,cgs,selection,choices=inputs()
        base=dict(selection=selection,choices=choices,expected_source_digest=hashlib.sha256(data).hexdigest(),expected_cgs_digest=digest(cgs),trusted_project=True)
        for field,value in [("expected_source_digest","0"*64),("expected_cgs_digest","0"*64),("trusted_project",False)]:
            with self.subTest(field=field),self.assertRaises(ValueError):plan_adoption(data,mapping,cgs,**dict(base,**{field:value}))
        valid=plan(data,mapping,cgs,selection,choices)
        self.assertEqual(verify_plan(valid,data,mapping,cgs,**base),valid)
        with self.assertRaises(ValueError):verify_plan(AdoptionPlan(valid.payload+b" "),data,mapping,cgs,**base)

    def test_unknown_behavior_cannot_be_acknowledged_away(self):
        data,mapping,cgs,selection,choices=inputs();value=json.loads(data)
        value["objects"][oid(2)]["opaque"]=[dict(id="script",sha256="b"*64,critical=True,reason="unknown behavior")]
        choices["legacy_dispositions"]=[dict(object_id=oid(2),opaque_id="script",sha256="b"*64,action="disable_before_play")]
        result=plan(canonical(value),mapping,cgs,selection,choices).to_dict()
        self.assertFalse(result["candidate_valid"]);self.assertFalse(result["play_eligible"]);self.assertFalse(result["legacy_disablement_plan"][0]["executable"])
        choices["legacy_dispositions"][0]["sha256"]="c"*64
        with self.assertRaisesRegex(ValueError,"stale legacy"):plan(canonical(value),mapping,cgs,selection,choices)

    def test_selected_dependency_closure_blocks_unknown(self):
        data,mapping,cgs,selection,choices=inputs();value=json.loads(data)
        value["objects"][oid(2)]["dependencies"]=[dict(kind="behavior",target=oid(3))]
        value["objects"][oid(3)]["opaque"]=[dict(id="script",sha256="b"*64,critical=True,reason="unknown behavior")]
        del choices["objects"][oid(3)]
        result=plan(canonical(value),mapping,cgs,[oid(2)],choices).to_dict();self.assertFalse(result["candidate_valid"])
        value["objects"][oid(2)]["dependencies"]=[]
        self.assertTrue(plan(canonical(value),mapping,cgs,[oid(2)],choices).to_dict()["candidate_valid"])

    def test_parent_is_not_fabricated_runtime_entity_id(self):
        data,mapping,cgs,selection,choices=inputs();value=json.loads(data);value["objects"][oid(3)]["parent_id"]=oid(2)
        result=plan(canonical(value),mapping,cgs,selection,choices).to_dict();self.assertFalse(result["candidate_valid"])
        objects=result["proposed_cgs"]["modes"][0]["world"]["contract"]["objects"]
        self.assertEqual(objects[1]["relationships"][_gde.PARENT_ROLE],[actor_id(mapping,oid(2))])
        self.assertEqual(result["proposed_cgs"]["modes"][0]["actors"][1]["components"][0]["defaults"]["parent_entity_id"],0)

    def test_missing_transform_is_reported_not_defaulted(self):
        data,mapping,cgs,selection,choices=inputs();value=json.loads(data);del value["objects"][oid(2)]["fields"]["transform.scale"]
        result=plan(canonical(value),mapping,cgs,selection,choices).to_dict();self.assertFalse(result["candidate_valid"])
        self.assertTrue(any(r["code"]=="incomplete_transform" for r in result["losses"]))

    def test_assets_native_write_preview_and_scope_preservation(self):
        from native_authoring_contract import inspect_capture
        import unity_authoring as reader
        data,mapping,cgs,selection,choices=inputs();value=json.loads(data)
        value["objects"][oid(2)]["fields"]["presentation.asset"]=dict(asset_id="unity_mesh",asset_type="MESH",status="LINKED",resolved_path="Assets/mesh.asset")
        choices["objects"][oid(2)]["asset_role"]="project.visual.v1";data=canonical(value)
        base=reader.capture(data,mapping,enable_writes=True).admit();changed=base.to_dict()["inspection"]["capture"]
        changed["objects"][oid(2)]["fields"]["transform.position"]["x"]="8"
        target=inspect_capture(changed,mapping,reader.policy(enable_writes=True)).admit()
        result=plan(data,mapping,cgs,selection,choices,native_target=target).to_dict()
        self.assertTrue(result["candidate_valid"],result["losses"]);self.assertEqual(result["native_write_preview"][0]["edits"][0]["fields"]["transform.position"]["x"],"8000000")
        self.assertEqual(result["proposed_cgs"]["assets"][-1]["source"],"Assets/mesh.asset")

    def test_gde_removal_binding_and_cycle_atomicity(self):
        data,mapping,cgs,selection,choices=inputs();current=plan(data,mapping,cgs,selection,choices).to_dict()["proposed_cgs"]
        mode=current["modes"][0];obj=mode["world"]["contract"]["objects"]
        ops=[dict(operation_id="parent",kind="reparent_world_object",mode_id="reference",object_id=obj[1]["id"],expected_digest=digest(obj[1]),parent_id=obj[0]["id"])]
        def apply(ops,source=current):return _gde.NativeAdoptionExecutor(validate=factory.compile_portable_cgs).execute(dict(schema=_gde.SCHEMA,expected_cgs_digest=digest(source),operations=ops),source).proposed_cgs
        parented=apply(ops);self.assertNotEqual(parented,current)
        ops.append(dict(operation_id="cycle",kind="reparent_world_object",mode_id="reference",object_id=obj[0]["id"],expected_digest=digest(obj[0]),parent_id=obj[1]["id"]))
        before=encode(current)
        with self.assertRaisesRegex(ValueError,"cyclic"):apply(ops)
        self.assertEqual(before,encode(current))
        remove=[dict(operation_id="remove",kind="remove_actor",mode_id="reference",actor_id=mode["actors"][0]["id"],expected_digest=digest(mode["actors"][0]))]
        with self.assertRaises(ValueError):apply(remove)
        remove.insert(0,dict(operation_id="world",kind="remove_world_object",mode_id="reference",object_id=obj[0]["id"],expected_digest=digest(obj[0])))
        self.assertEqual(len(apply(remove)["modes"][0]["actors"]),1)


    def test_package_install_noop_and_configuration_conflict(self):
        args=list(inputs());data,mapping,cgs,selection,choices=args
        cat,operation=damage_package(mapping,selection)
        add_damage_choices(cgs,choices)
        choices["packages"]=[operation]
        first=plan(*args,gameplay_catalog=cat).to_dict();self.assertTrue(first["candidate_valid"],first["losses"])
        second=plan(data,mapping,first["proposed_cgs"],selection,choices,gameplay_catalog=cat).to_dict()
        self.assertTrue(second["noop"],second["typed_operations"])
        choices["packages"][0]["package_hash"]="0"*64
        with self.assertRaises(ValueError):plan(data,mapping,cgs,selection,choices,gameplay_catalog=cat)

    def test_typed_playback_and_undeclared_event(self):
        data,mapping,cgs,selection,choices=inputs();value=json.loads(data)
        value["objects"][oid(2)]["fields"]["binding.playback"]=dict(binding_id="import.hit",event_name="combat.hit",playback_kind="Audio",asset=dict(asset_id="audio_hit",asset_type="AUDIO_CLIP",status="LINKED",resolved_path="Assets/hit.wav"))
        choices["objects"][oid(2)]["playback"]=dict(semantic_action="play",entity_selector="SourceEntity",parameters={},enabled=True,priority=1)
        data=canonical(value);bad=plan(data,mapping,cgs,selection,choices).to_dict();self.assertFalse(bad["candidate_valid"])
        cgs["semantic_events"]=[dict(name="combat.hit",payload_fields=[],version="1.0.0")];rehash(cgs)
        good=plan(data,mapping,cgs,selection,choices).to_dict();self.assertTrue(good["candidate_valid"],good["losses"])
        binding=good["proposed_cgs"]["semantic_bindings"]["bindings"][0]
        self.assertEqual(binding["asset"],dict(id="audio_hit",asset_type="AudioClip",status="Linked"))
        self.assertTrue(plan(data,mapping,good["proposed_cgs"],selection,choices).to_dict()["noop"])
        choices["objects"][oid(2)]["playback"]["entity_selector"]="Global"
        self.assertFalse(plan(data,mapping,cgs,selection,choices).to_dict()["candidate_valid"])

    def test_source_loss_review_is_bound(self):
        import unity_authoring
        data,mapping,cgs,selection,choices=inputs();value=json.loads(data);value["objects"][oid(2)]["fields"]["transform.position"]["x"]="1.0000005";data=canonical(value)
        self.assertFalse(plan(data,mapping,cgs,selection,choices).to_dict()["candidate_valid"])
        review=unity_authoring.capture(data,mapping,enable_writes=True).loss_digest
        good=plan(data,mapping,cgs,selection,choices,accepted_loss_digest=review).to_dict();self.assertTrue(good["candidate_valid"],good["losses"])
        self.assertFalse(plan(data,mapping,cgs,selection,choices,accepted_loss_digest="0"*64).to_dict()["candidate_valid"])

    def test_binding_edits_use_record_cas_and_final_asset_validation(self):
        current=plan(*inputs()).to_dict()['proposed_cgs']
        current['assets']=[dict(id='mesh',asset_type='MESH',status='LINKED',source='Assets/mesh.asset')];rehash(current)
        obj=current['modes'][0]['world']['contract']['objects'][0]
        op=dict(operation_id='binding',kind='set_asset_binding',mode_id='reference',object_id=obj['id'],expected_digest=digest(obj),role='project.visual.v1',asset=dict(id='mesh',asset_type='MESH',status='LINKED'))
        def apply(source,operation):return _gde.NativeAdoptionExecutor(validate=factory.compile_portable_cgs).execute(dict(schema=_gde.SCHEMA,expected_cgs_digest=digest(source),operations=[operation]),source).proposed_cgs
        bound=apply(current,op)
        with self.assertRaisesRegex(ValueError,'stale World'):apply(bound,op)
        op['expected_digest']=digest(bound['modes'][0]['world']['contract']['objects'][0]);op['asset']=None
        removed=apply(bound,op);self.assertEqual(removed,current)
        op['expected_digest']=digest(obj);op['asset']=dict(id='missing',asset_type='MESH',status='UNRESOLVED')
        with self.assertRaises(ValueError):apply(current,op)

    def test_multiple_package_order_is_idempotent_and_capability_mapping_refused(self):
        data,mapping,cgs,selection,choices=inputs();catalog,operation=damage_package(mapping,selection)
        packages=[];operations=[]
        for number in [1,2]:
            package=catalog.resolve(operation['package_id'],operation['package_hash'])
            package.update(id='project.data'+str(number)+'.v1',systems=[],requirements=dict(component_type_ids=[],system_ids=[],capability_ids=[]),component_schemas=[dict(type_id=10000+number,name='PROJECT_DATA'+str(number),source='gcl',defaults=dict(value=number))])
            packages.append(package)
        catalog=type(catalog)(packages)
        for descriptor in catalog.descriptors():operations.append(dict(operation,operation_id=descriptor['id'],package_id=descriptor['id'],package_hash=descriptor['package_hash']))
        choices['packages']=operations
        first=plan(data,mapping,cgs,selection,choices,gameplay_catalog=catalog).to_dict();self.assertTrue(first['candidate_valid'],first['losses'])
        self.assertTrue(plan(data,mapping,first['proposed_cgs'],selection,choices,gameplay_catalog=catalog).to_dict()['noop'])
        packages[0]['capability_declarations']=[dict(id='project.test.v1',allowed_kinds=[])]
        catalog=type(catalog)(packages);choices['packages'][0]['package_hash']=catalog.descriptors()[0]['package_hash']
        with self.assertRaisesRegex(ValueError,'capability materialization'):plan(data,mapping,cgs,selection,choices,gameplay_catalog=catalog)

    def test_dirty_or_play_blocks_even_excluded_objects(self):
        data,mapping,cgs,selection,choices=inputs();value=json.loads(data)
        for kind in ["dirty","play"]:
            changed=copy.deepcopy(value)
            if kind=="dirty":changed["source"]["documents"][0]["dirty"]=True
            else:changed["source"]["play_mode"]=True
            self.assertFalse(plan(canonical(changed),mapping,cgs,selection,choices).to_dict()["candidate_valid"])

    def test_explicit_new_mode_and_cancellation(self):
        data,mapping,cgs,selection,choices=inputs();choices["mode_id"]="imported"
        mode=copy.deepcopy(cgs["modes"][0]);mode.update(id="imported",is_default=False);choices["new_mode"]=mode
        before=encode(cgs);result=plan(data,mapping,cgs,selection,choices).to_dict()
        self.assertTrue(result["candidate_valid"],result["losses"]);self.assertEqual(encode(cgs),before)
        self.assertEqual(len(result["proposed_cgs"]["modes"]),2)

    def test_invalid_choice_component_and_geometry_fail_closed(self):
        for kind in ["unknown_component","bad_geometry"]:
            args=list(inputs());choice=args[4]["objects"][oid(2)]
            if kind=="unknown_component":choice["components"]=[dict(type_id=9999,name="COMP_FAKE_V1",defaults={})]
            else:choice["geometry_profile"]="world.arbitrary_mesh.v1"
            result=plan(*args).to_dict();self.assertFalse(result["candidate_valid"])
            self.assertTrue(any(r["code"]=="gde_factory_rejected" for r in result["losses"]))

    def test_legacy_movement_cannot_claim_structured_compatibility(self):
        args=list(inputs());cgs=args[2]
        cgs["modes"][0]["systems"]=[dict(id="MovementSystem",phase="Simulation",reads=[1,5],writes=[1],depends_on=[],deterministic=True)]
        rehash(cgs);result=plan(*args).to_dict();self.assertFalse(result["candidate_valid"])
        self.assertTrue(any(r["code"]=="uncertified_structured_transform_system" for r in result["losses"]),result["losses"])

    def test_gde_unknown_and_stale_operation_no_side_effect(self):
        args=inputs();current=plan(*args).to_dict()["proposed_cgs"];before=encode(current)
        executor=_gde.NativeAdoptionExecutor(validate=factory.compile_portable_cgs)
        for op in [dict(operation_id="bad",kind="write_file",path="outside"),dict(operation_id="bad",kind="remove_actor",mode_id="reference",actor_id=current["modes"][0]["actors"][0]["id"],expected_digest="0"*64)]:
            with self.assertRaises(ValueError):executor.execute(dict(schema=_gde.SCHEMA,expected_cgs_digest=digest(current),operations=[op]),current)
        self.assertEqual(encode(current),before)


def add_damage_choices(cgs,choices):
    defaults={100:dict(current=100000000,max=100000000,regen_rate=0,is_invincible=False),101:dict(amount=10000000)}
    names={100:"COMP_HEALTH_V1",101:"COMP_DAMAGE_V1"}
    cgs["component_schemas"]=[dict(type_id=tid,name=names[tid],source="dcl.combat",defaults=values) for tid,values in defaults.items()]
    for choice in choices["objects"].values(): choice["components"]=[dict(type_id=tid,name=names[tid],defaults=copy.deepcopy(values)) for tid,values in defaults.items()]
    rehash(cgs)


def damage_package(mapping,selection):
    Catalog=importlib.import_module("gde.src.domain_dsl.typed_operations.gameplay_catalog").GameplayCatalog
    system=dict(id="DamageSystem",phase="Simulation",reads=[100,101],writes=[100,101],depends_on=[],deterministic=True)
    package=dict(schema="xace.gameplay_authoring_package.v1",id="project.explicit_damage.v1",version="1.0.0",aliases=["Explicit damage behavior"],component_schemas=[],systems=[system],capability_declarations=[],requirements=dict(component_type_ids=[100,101],system_ids=["DamageSystem"],capability_ids=[]),templates=[],configurations=[dict(id="default",defaults={})])
    catalog=Catalog([package],supported_systems=[system]);descriptor=catalog.descriptors()[0]
    operation=dict(operation_id="package.damage",kind="install_gameplay_package",explanation="User chose 10 health damage once",package_id=package["id"],package_hash=descriptor["package_hash"],mode_id="reference",actor_ids=sorted(actor_id(mapping,k) for k in selection),capability_targets=[],template_id="",configuration_id="default")
    return catalog,operation

if __name__=="__main__":unittest.main()
