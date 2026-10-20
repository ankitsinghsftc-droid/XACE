import sys, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from native_saved_changes import SavedRevision, SavedChangeBatcher


def revision(value):
    return SavedRevision(value*64,'b'*64,'c'*64)


class SavedChangeTests(unittest.TestCase):
    def test_burst_coalesces_only_latest_saved_revision(self):
        b=SavedChangeBatcher(1)
        self.assertEqual(b.observe(revision('a'),0),'waiting')
        self.assertEqual(b.observe(revision('d'),0.9),'waiting')
        self.assertEqual(b.observe(revision('d'),1.1),'waiting')
        self.assertEqual(b.observe(revision('d'),2),'review_available')
        self.assertEqual(b.observe(revision('d'),9),'unchanged')

    def test_reverting_after_another_notification_is_a_new_change(self):
        b=SavedChangeBatcher(1)
        for rev,start in [(revision('a'),0),(revision('d'),2),(revision('a'),4)]:
            self.assertEqual(b.observe(rev,start),'waiting')
            self.assertEqual(b.observe(rev,start+1),'review_available')

    def test_dirty_or_failed_capture_resets_quiet_window(self):
        b=SavedChangeBatcher(1);b.observe(revision('a'),0);b.invalidate()
        self.assertEqual(b.observe(revision('a'),5),'waiting')
        self.assertEqual(b.observe(revision('a'),6),'review_available')

    def test_restart_requires_fresh_stable_observations(self):
        b=SavedChangeBatcher(1);b.observe(revision('a'),0);b.observe(revision('a'),1)
        restarted=SavedChangeBatcher(1)
        self.assertEqual(restarted.observe(revision('a'),2),'waiting')
        self.assertEqual(restarted.observe(revision('a'),3),'review_available')

    def test_invalid_identity_and_clock_never_notify(self):
        with self.assertRaises(ValueError):SavedRevision('x'*64,'a'*64,'b'*64)
        for value in [0,-1,float('nan'),float('inf'),True]:
            with self.assertRaises(ValueError):SavedChangeBatcher(value)
        b=SavedChangeBatcher(1);b.observe(revision('a'),2)
        with self.assertRaises(ValueError):b.observe(revision('a'),1)
        self.assertEqual(b.observe(revision('a'),3),'waiting')
        with self.assertRaises(ValueError):b.observe(revision('a'),float('nan'))

class HostNotificationTests(unittest.TestCase):
    def test_notifications_do_not_publish_or_authorize(self):
        import tempfile
        from unittest.mock import patch
        from test_native_materialization_host import HostTests
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);host,context=HostTests().fixture(root)
            before={p.name:p.read_bytes() for p in root.iterdir() if p.is_file()}
            with patch('time.monotonic',side_effect=[0,1,2]):
                self.assertEqual(host.poll_saved_changes()['state'],'waiting')
                report=host.poll_saved_changes()
                self.assertEqual(report['state'],'review_available')
                self.assertFalse(report['can_commit'])
                self.assertEqual(host.poll_saved_changes()['state'],'unchanged')
            self.assertFalse(host.review._sessions)
            self.assertEqual(before,{p.name:p.read_bytes() for p in root.iterdir() if p.is_file()})
            self.assertFalse((root/'.xace/authoring-baseline.native.json').exists())

    def test_failed_capture_resets_batch_and_pending_recovery_blocks_notification(self):
        import tempfile
        from unittest.mock import patch
        from test_native_materialization_host import HostTests
        with tempfile.TemporaryDirectory() as d:
            host,_=HostTests().fixture(Path(d));provider=host.review.context_provider
            with patch('time.monotonic',return_value=0):host.poll_saved_changes()
            with patch.object(host.review,'context_provider',side_effect=OSError('capture failed')):
                with self.assertRaises(OSError):host.poll_saved_changes()
            with patch('time.monotonic',return_value=5):
                self.assertEqual(host.poll_saved_changes()['state'],'waiting')
            (Path(d)/'.xace/authoring-transactions/incomplete').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError,'recovery blocks'):host.poll_saved_changes()

if __name__=='__main__':unittest.main()
