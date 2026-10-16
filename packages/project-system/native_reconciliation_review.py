"""Host-owned, principal-bound NEC-008 review sessions. No commit capability."""
import copy
import hashlib
import hmac
import secrets
import threading
import time

from authoring_identity import require
from native_adoption import encode
from native_reconciliation_plan import plan_reconciliation


class ReconciliationReview:
    def __init__(self, context_provider, *, lifetime_seconds=900):
        require(callable(context_provider),'host context provider required')
        self.context_provider=context_provider;self.lifetime=lifetime_seconds
        self._key=secrets.token_bytes(32);self._sessions={};self._lock=threading.RLock()

    def _plan(self,resolutions=None):
        context=self.context_provider()
        require(type(context) is dict and 'resolutions' not in context,'host owns reconciliation context')
        return plan_reconciliation(**context,resolutions=resolutions)

    def _get(self,principal,token):
        require(type(principal) is str and bool(principal),'authenticated principal required')
        session=self._sessions.get(token)
        require(session is not None and hmac.compare_digest(session['principal'],principal),'unknown review session')
        require(time.monotonic()-session['created']<=self.lifetime,'review expired; refresh')
        require(self._plan().payload==session['original'].payload,'review inputs changed; refresh')
        return session

    def open(self,principal):
        require(type(principal) is str and 0<len(principal)<=256,'authenticated principal required')
        with self._lock:
            now=time.monotonic()
            self._sessions={k:v for k,v in self._sessions.items() if now-v['created']<=self.lifetime}
            require(len(self._sessions)<64,'review session limit')
            plan=self._plan();token=secrets.token_urlsafe(32)
            self._sessions[token]=dict(principal=principal,created=now,original=plan,plan=plan,resolutions={})
            return dict(token=token,proposal_digest=plan.sha256,report=plan.to_dict())

    def resolve(self,principal,token,expected_digest,resolutions):
        with self._lock:
            session=self._get(principal,token)
            require(session['plan'].sha256==expected_digest,'concurrent review edit; refresh')
            plan=self._plan(resolutions)
            # Re-read the origin after building the replacement to catch host drift.
            self._get(principal,token)
            session.update(plan=plan,resolutions=copy.deepcopy(resolutions))
            return dict(token=token,proposal_digest=plan.sha256,report=plan.to_dict())

    def approve(self,principal,token,expected_digest):
        with self._lock:
            session=self._get(principal,token);plan=self._plan(session['resolutions'])
            require(plan.payload==session['plan'].payload and plan.sha256==expected_digest,'stale reviewed proposal')
            require(plan.to_dict()['reviewable'],'blocked proposal cannot be approved')
            receipt=dict(schema='xace.native_reconciliation_review_approval.v1',principal=principal,
                         session=token,proposal_digest=plan.sha256,identities=plan.to_dict()['identities'],
                         can_commit=False,requires_coordinator=True)
            receipt['signature']=hmac.new(self._key,encode(receipt),hashlib.sha256).hexdigest()
            return receipt

    def verify_approval(self,principal,receipt):
        require(type(receipt) is dict,'invalid approval')
        unsigned=copy.deepcopy(receipt);signature=unsigned.pop('signature',None)
        require(type(signature) is str and hmac.compare_digest(signature,hmac.new(self._key,encode(unsigned),hashlib.sha256).hexdigest()),'invalid approval signature')
        with self._lock:
            session=self._get(principal,receipt['session'])
            require(receipt['principal']==principal and receipt['proposal_digest']==session['plan'].sha256,'approval principal/proposal mismatch')
            fresh=self._plan(session['resolutions'])
            require(fresh.payload==session['plan'].payload and fresh.to_dict()['reviewable'],'approval no longer current')
            return fresh

    def cancel(self,principal,token):
        # Cancellation works even after source drift and never changes either store.
        with self._lock:
            session=self._sessions.get(token)
            require(session is not None and session['principal']==principal,'unknown review session')
            del self._sessions[token]
