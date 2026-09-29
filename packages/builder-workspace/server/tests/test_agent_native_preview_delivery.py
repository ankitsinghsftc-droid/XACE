import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent_host.event_stream import _dynamic_tool_preview_ingress


class NativePreviewDeliveryTests(unittest.TestCase):
    def item(self):
        return {'type':'mcpToolCall','server':'xace','tool':'xace.submit_proposal','status':'completed',
                'result':{'structuredContent':{'tool_name':'xace.submit_proposal','status':'completed',
                    'read_only':False,'data':{'proposal_ingress':{'accepted':True,'status':'preview_created'}}}}}

    def parse(self,item,method='item/completed'):
        return _dynamic_tool_preview_ingress(SimpleNamespace(provider_id='codex_app_server',
            data={'codex_method':method,'params':{'item':item}}))

    def test_native_structured_and_text_envelopes(self):
        item = self.item()
        self.assertTrue(self.parse(item)['accepted'])
        payload = item['result'].pop('structuredContent')
        item['result']['content'] = [{'type':'text','text':json.dumps(payload)}]
        self.assertTrue(self.parse(item)['accepted'])

    def test_started_foreign_failed_and_non_proposal_calls_are_rejected(self):
        self.assertIsNone(self.parse(self.item(),'item/started'))
        for key,value in [('server','foreign'),('tool','xace.read_cgs'),('status','failed'),('error',{'message':'failed'})]:
            item = self.item(); item[key] = value
            self.assertIsNone(self.parse(item))
        item = self.item(); item['result']['isError'] = True
        self.assertIsNone(self.parse(item))

    def test_malformed_or_rejected_ingress_never_creates_preview(self):
        for value in (None,[],{'tool_name':'xace.submit_proposal','status':'failed'}):
            item = self.item(); item['result']['structuredContent'] = value
            self.assertIsNone(self.parse(item))
        item = self.item()
        item['result']['structuredContent']['data']['proposal_ingress']['accepted'] = False
        self.assertIsNone(self.parse(item))
