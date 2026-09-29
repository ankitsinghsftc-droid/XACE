import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent_host.codex_linux_profile import adapt_params, profile_config, DISABLED_FEATURES


class LinuxProfileTests(unittest.TestCase):
    def adapt(self, method, params):
        return adapt_params(method,params,cwd='/capsule',runtime_root='/opt/codex')

    def test_profile_is_read_only_network_denied_and_native_features_off(self):
        value = profile_config('/capsule','/opt/codex')
        self.assertEqual(value['approval_policy'],'never')
        self.assertFalse(value['permissions']['xace_capsule']['network']['enabled'])
        self.assertEqual(value['permissions']['xace_capsule']['filesystem'],
                         {':minimal':'read','/opt/codex':'read','/capsule':'read'})
        self.assertTrue(all(value['features'][key] is False for key in DISABLED_FEATURES))
        self.assertNotIn('sandbox_mode',value)

    def test_start_reasserts_policy_without_unsupported_fields(self):
        original = {'sandbox':'read-only','approvalPolicy':'never','allowProviderModelFallback':True,
                    'config':{'features':{'shell_tool':True},'tools':{'view_image':True}}}
        saved = copy.deepcopy(original)
        value = self.adapt('thread/start',original)
        self.assertNotIn('sandbox',value)
        self.assertNotIn('allowProviderModelFallback',value)
        self.assertNotIn('tools',value['config'])
        self.assertFalse(value['config']['features']['shell_tool'])
        self.assertEqual(original,saved)

    def test_turn_cannot_change_capsule_or_policy(self):
        valid = {'cwd':'/capsule','approvalPolicy':'never','sandboxPolicy':{
            'type':'readOnly','access':{'type':'restricted','includePlatformDefaults':False,'readableRoots':['/capsule']}}}
        self.assertNotIn('sandboxPolicy',self.adapt('turn/start',valid))
        for key,bad in [('cwd','/other'),('approvalPolicy','on-request'),('sandboxPolicy',{'type':'readOnly'})]:
            with self.assertRaises(ValueError): self.adapt('turn/start',{**valid,key:bad})

    def test_resume_and_fork_preserve_supported_history_semantics(self):
        value = self.adapt('thread/resume',{'threadId':'t','excludeTurns':True,'initialTurnsPage':{'limit':20}})
        self.assertTrue(value['excludeTurns'])
        self.assertNotIn('initialTurnsPage',value)
        self.assertEqual(self.adapt('thread/fork',{'threadId':'t','lastTurnId':'cut'})['lastTurnId'],'cut')
        with self.assertRaises(ValueError): self.adapt('thread/fork',{'threadId':'t','beforeTurnId':'cut'})

    def test_foreign_mcp_or_privileged_override_rejected(self):
        with self.assertRaises(ValueError): self.adapt('thread/start',{'config':{'mcp_servers':{'other':{}}}})
        with self.assertRaises(ValueError): self.adapt('thread/start',{'sandbox':'danger-full-access'})
        with self.assertRaises(ValueError): self.adapt('thread/start',{'approvalPolicy':'on-request'})

    def test_native_xace_mcp_configuration_preserved(self):
        server = {'command':'/python','args':['/fixed-proxy.py'],'required':True}
        value = self.adapt('thread/start',{'config':{'mcp_servers':{'xace':server}}})
        self.assertEqual(value['config']['mcp_servers'],{'xace':server})
