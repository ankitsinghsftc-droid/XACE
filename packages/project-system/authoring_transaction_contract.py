"""NEC-009 host participant contract. No runtime mutation/activation authority."""
from dataclasses import dataclass
from typing import Protocol

from native_adoption import digest, encode
from authoring_identity import require


@dataclass(frozen=True)
class TransactionRequest:
    transaction_id: str
    proposal_digest: str
    participant_requests: dict
    activation_record: dict
    verification_record: dict | None = None
    recovery_payload: dict | None = None


class Participant(Protocol):
    """Trusted, registered host implementation, never imported from a journal.

    prepare is repeatable and MUST NOT publish. Its token contains all durable
    before/after identity and recovery references, independent of process memory.
    inspect returns before/after/partial/conflict from actual store state plus dependencies.
    publish/restore are repeatable and must preserve displaced/newer work.
    """
    identity: dict
    def prepare(self, transaction_id:str, request:dict, directory) -> dict: ...
    def inspect(self, token:dict, directory) -> str: ...
    def publish(self, token:dict, directory) -> dict: ...
    def restore(self, token:dict, directory) -> dict: ...


def validate_request(request:TransactionRequest, participants:dict):
    import re
    require(type(request) is TransactionRequest,'typed transaction request required')
    require(re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',request.transaction_id) is not None,'invalid transaction ID')
    require(re.fullmatch(r'[a-f0-9]{64}',request.proposal_digest) is not None,'invalid proposal digest')
    require(type(request.participant_requests) is dict and set(request.participant_requests)==set(participants),'participant set mismatch')
    require(1<=len(participants)<=8,'participant limit')
    require(request.activation_record=={'performed':False,'policy':'preserve_existing_session_require_explicit_restart'},'coordinator cannot activate runtime')
    encode(request.participant_requests)
    if request.verification_record is not None:
        require(type(request.verification_record) is dict,'invalid verification binding')
        encode(request.verification_record)
    if request.recovery_payload is not None:
        require(type(request.recovery_payload) is dict,'invalid recovery payload')
        encode(request.recovery_payload)


def receipt(participant,token,state):
    require(state in {'before','after','conflict'},'invalid participant state')
    return dict(schema='xace.authoring_participant_receipt.v1',participant=digest(participant.identity),token_digest=digest(token),state=state)
