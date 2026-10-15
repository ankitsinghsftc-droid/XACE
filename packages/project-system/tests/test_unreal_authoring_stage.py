import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from authoring_identity import canonical
from unreal_authoring_stage import inventory, stage


class UnrealStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root/'source'
        (self.source/'Content/Maps').mkdir(parents=True)
        self.project = self.source/'Fixture.uproject'
        self.project.write_text(json.dumps(dict(FileVersion=3)))
        (self.source/'Content/Maps/World.umap').write_bytes(b'opaque-native-binary\x00\xff')

    def digest(self): return hashlib.sha256(canonical(inventory(self.project))).hexdigest()

    def test_binary_copy_receipt_without_source_write_or_launch(self):
        before = inventory(self.project)
        result = stage(self.project, self.root/'copy', trusted_project=True,
                       expected_inventory_digest=self.digest())
        self.assertEqual(inventory(self.project), before)
        self.assertFalse(result['engine_launched'])
        self.assertEqual((self.root/'copy/Content/Maps/World.umap').read_bytes(),
                         (self.source/'Content/Maps/World.umap').read_bytes())

    def test_untrusted_stale_nested_and_existing_destinations_refused(self):
        for trust, digest, dest in [(False,self.digest(),self.root/'copy'),
                                    (True,'0'*64,self.root/'copy'),
                                    (True,self.digest(),self.source/'nested'),
                                    (True,self.digest(),self.source)]:
            with self.subTest(dest=dest,trust=trust), self.assertRaises(ValueError):
                stage(self.project,dest,trusted_project=trust,expected_inventory_digest=digest)

    def test_cpp_project_requires_explicit_supported_build_profile(self):
        self.project.write_text(json.dumps(dict(Modules=[dict(Name='Gameplay')])))
        with self.assertRaises(ValueError): inventory(self.project)

    def test_resolved_nested_destination_is_refused(self):
        (self.root/'intermediate').mkdir()
        with self.assertRaises(ValueError):
            stage(self.project, self.root/'intermediate/../source/nested',
                  trusted_project=True, expected_inventory_digest=self.digest())

    def test_mid_copy_source_drift_never_produces_approved_receipt(self):
        import shutil
        original = shutil.copyfile
        def drifting(source, destination):
            result = original(source, destination)
            if str(source).endswith('.umap'): Path(source).write_bytes(b'newer native save')
            return result
        expected = self.digest()
        with patch('unreal_authoring_stage.shutil.copyfile', side_effect=drifting):
            with self.assertRaises(ValueError):
                stage(self.project,self.root/'copy',trusted_project=True,
                      expected_inventory_digest=expected)
        self.assertFalse((self.root/'copy/xace-trusted-copy.json').exists())
        self.assertEqual((self.source/'Content/Maps/World.umap').read_bytes(), b'newer native save')


if __name__=='__main__': unittest.main()
