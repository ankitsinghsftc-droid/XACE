"""Register an existing native-generated stage for explicit reviewed publication.

Registration uses a fresh native capture. Subsequent review calls validate every
source byte and the complete source inventory; they never silently regenerate a
stage or replace the approved target with readback from another revision.
"""
import copy
from authoring_identity import require,canonical
from authoring_transaction_files import confined,sha
from native_setup_plan import NativeSetupPlan,verify_setup
from native_setup_bundle import NativeSetupBundle

class VerifiedNativeSetupStage:
    def __init__(self,plan,cgs,gateway):
        require(type(plan) is NativeSetupPlan,'typed setup plan required')
        require(plan.to_dict()['engine']==gateway.engine,'stage engine mismatch')
        self.plan=plan;self.gateway=gateway;self.cgs=canonical(cgs)
        self.inventory=gateway.capture()
        verify_setup(plan,cgs,self.inventory)
        self.hashes=gateway._files()
        self.files={p:confined(gateway.root,p).read_bytes() for p in sorted(self.hashes)}
        require(all(sha(b)==self.hashes[p] for p,b in self.files.items()),'stage changed during registration')
        require(gateway._files()==self.hashes,'stage changed during registration')
        NativeSetupBundle(gateway.root,engine=gateway.engine,allowed_paths=list(self.files))
        require(sum(map(len,self.files.values()))<=8*1024**2,'setup publication byte limit')
    def __call__(self,cgs):
        require(canonical(cgs)==self.cgs,'setup CGS changed; explicit restaging required')
        require(self.gateway._files()==self.hashes,'native stage changed; explicit restaging required')
        return dict(plan=self.plan,native_inventory=self.inventory,files=copy.deepcopy(self.files))
