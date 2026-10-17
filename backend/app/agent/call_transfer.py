"""Direct SIP handoff helpers, matched to livekit-api 1.2.1/protocol 1.1.27."""
from datetime import timedelta
from livekit import api, rtc

RING_SECONDS = 45
REQUEST_SECONDS = 55
DEADLINE_SECONDS = 60


def caller_identity(participants):
    """Select an actual SIP caller, never an arbitrary browser/agent or second leg."""
    candidates = []
    legacy = []
    for p in participants:
        attrs = getattr(p, 'attributes', {}) or {}
        if attrs.get('sip.callStatus') in ('hangup', 'disconnected'):
            continue
        if getattr(p, 'kind', None) == rtc.ParticipantKind.PARTICIPANT_KIND_SIP or attrs.get('sip.callID'):
            candidates.append(p.identity)
        elif getattr(p, 'kind', None) is None and p.identity.startswith('sip_'):
            legacy.append(p.identity)
    found = candidates or legacy
    return found[0] if len(found) == 1 else None


def request(room_name, identity, destination):
    from app.services.outbound_call import validate_e164
    number = validate_e164(destination)
    return api.TransferSIPParticipantRequest(
        room_name=room_name, participant_identity=identity, transfer_to=f'tel:{number}',
        play_dialtone=True, ringing_timeout=timedelta(seconds=RING_SECONDS))


def receipt(response):
    """Empty/legacy/ongoing replies are not evidence of a completed transfer."""
    status = getattr(response, 'status', None)
    result = {'status': 'completed' if status == api.SIPTransferStatus.STS_TRANSFER_SUCCESSFUL
              else 'failed' if status == api.SIPTransferStatus.STS_TRANSFER_FAILED else 'unknown'}
    reason = getattr(response, 'reason', None)
    if reason is not None:
        try:
            result['reason'] = api.SIPTransferReason.Name(reason)
        except ValueError:
            result['reason'] = 'unknown'
    sip = getattr(response, 'sip_status', None)
    if sip is not None and getattr(sip, 'code', 0):
        result['sip_status_code'] = sip.code
    return result


def error_details(exc):
    """Operational diagnostics without raw provider text, numbers, or credentials."""
    result = {'error_type': type(exc).__name__}
    code = getattr(exc, 'code', None)
    if code is not None:
        result['error_code'] = str(code)[:64]
    sip = getattr(exc, 'sip_status_code', None)
    if sip is not None:
        result['sip_status_code'] = sip
    return result
