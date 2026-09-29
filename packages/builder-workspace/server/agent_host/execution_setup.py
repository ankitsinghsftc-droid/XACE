"""Backend-neutral setup status/control facade for the existing local UI."""
from codex_backend_provisioning import ProvisioningJob


class ExecutionBackendSetup:
    def __init__(self,backend,*,invalidate=lambda:None):
        self.backend=backend
        self.invalidate=invalidate
        self.provisioning=ProvisioningJob(backend,invalidate)

    def status(self):
        health=self.backend.inspect()
        return {'schema':'xace.agent_runtime_setup.v1','runtime':{
            'ready':health.ready,'state_error':None if health.ready else health.code,
            'active':{'version':health.runtime_version,'executable_path':'','provenance_basis':'verified_isolated_runtime'} if health.ready else None,
            'active_health':{'code':health.code},'execution_backend':health.to_dict(),
            'setup_mode':'isolated_backend','preferred_auth_flow':'device_code',
            'message':health.message},
            'job':self.provisioning.status(),
            'override_active':False,'automatic_acquisition':False}

    def detect(self):
        return {'candidate_path':'','verified':False,'execution_backend':self.backend.inspect().to_dict()}

    def start(self,action,payload):
        if action not in {'install','update','repair','rollback','remove','recover'}:
            raise ValueError('invalid_runtime_action')
        if not isinstance(payload,dict) or payload.get('confirm') is not True:
            raise ValueError('confirmation_required')
        if action in {'install','repair'} and set(payload)=={'confirm','runtime_package'}:
            self.provisioning.start(payload['runtime_package'])
            return self.status()
        # The verified immutable runtime is operator-provisioned, never changed
        # by an arbitrary executable path or a model-triggered action.
        if action in {'install','repair','recover'} and set(payload)=={'confirm'}:
            self.invalidate()
            return self.status()
        raise ValueError('backend_operation_requires_operator_setup')

    def cancel(self):
        self.provisioning.cancel()
        return self.status()
    def close(self): self.provisioning.close()
