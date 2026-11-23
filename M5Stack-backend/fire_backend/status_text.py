"""Reviewed single-line Norwegian status text; diagnostic detail stays in logs.

28 UTF-8 bytes also fits the existing FIRE status field before its byte-based
cutoff. Never shorten arbitrary text by slicing or adding an ellipsis.
"""
import unicodedata

VERSION = 'fire-status-text-v1'
MAX_CHARS = 28
MAX_UTF8_BYTES = 28

TEXT = {
    'preparing':'Klargjør appen',
    'new':'Lager appen',
    'update':'Oppdaterer appen',
    'repair':'Retter appen',
    'validating':'Sjekker kode',
    'compiling':'Kontrollerer appen',
    'testing':'Tester knapper og sensorer',
    'review':'Sjekker funksjon og design',
    'packaging':'Pakker appen',
    'sending':'Sender appen til FIRE',
    'ready':'Klar til kjøring',
    'repair_ready':'Ny versjon klar',
    'prepared':'Klar til feilretting',
    'queued':'Venter på ledig bygger',
    'api_wait':'Venter på AI-kapasitet',
    'interrupted':'Avbrutt. Velg Fiks feil',
    'unavailable':'Pakken er utilgjengelig',
    'not_found':'Ingen reparasjon funnet',
    'unknown':'Behandler appen',
    'background':'Bygger i bakgrunnen',
    'build_ready':'Appen er klar',
    'resumed':'Fortsett utviklingen',
    'dismissed':'Varslet er lukket',
    'failed':'Arbeidet mislyktes',
    'ai_output_limit':'AI-svaret ble avkuttet',
    'ai_refused':'AI avslo forespørselen',
    'ai_invalid_response':'AI ga ikke gyldig appkode',
    'ai_incomplete':'AI-svaret ble avbrutt',
    'test_failed':'Appen bestod ikke testen',
    'cancelled':'Byggingen ble avbrutt',
    'timeout':'Tidsavbrudd. Prøv igjen',
    'ai_busy':'AI er opptatt. Prøv igjen',
    'api_key':'Kontroller API-nøkkelen',
    'api_account':'Kontroller API-kontoen',
    'cost_limit':'Kostnadsgrensen er nådd',
    'unknown_price':'Modellen mangler pris',
    'network':'Nettverksfeil. Prøv igjen',
    'storage':'SD-kortet er ikke klart',
    'disk_full':'PC-lagringen er full',
    'firmware':'Firmware må oppdateres',
    'identity':'Appversjonen er ukjent',
    'scope':'Appen tilhører annen enhet',
    'expired':'Valget er utløpt',
    'busy':'En appoppgave pågår',
    'run_failed':'Kunne ikke starte appen',
    'invalid_event':'Ugyldig enhetsmelding',
    'no_speech':'Ingen tale. Prøv igjen',
    'audio_missing':'Opptaket kom ikke frem',
    'audio_failed':'Talesvaret feilet',
}


def checked(text):
    if (not text or text != unicodedata.normalize('NFC',text) or
            len(text)>MAX_CHARS or len(text.encode('utf-8'))>MAX_UTF8_BYTES or
            any(unicodedata.category(c).startswith('C') for c in text) or
            '...' in text or '…' in text):
        raise ValueError('Status must be a complete short NFC UTF-8 line')
    return text


for _text in TEXT.values():
    checked(_text)


def error_text(detail='',code=''):
    if isinstance(detail,str) and detail in {TEXT[k] for k in ('failed','test_failed','cancelled','timeout','ai_busy','api_key','api_account','network','storage','disk_full','firmware','identity','scope','expired','busy','run_failed','invalid_event','no_speech','audio_missing','audio_failed')}:
        return detail
    text=(str(code)+' '+str(detail)).casefold()
    choices=(
        (('ai_output_limit','svargrensen','svartokens','ai-svaret ble avkuttet'), 'ai_output_limit'),
        (('ai_refused','ai avslo'), 'ai_refused'),
        (('ai_invalid_response','ikke gyldig appkode'), 'ai_invalid_response'),
        (('ai_incomplete','ai-svaret ble avbrutt'), 'ai_incomplete'),
        (('cost_limit','kostnadsgrens','cost limit','budget_usd'), 'cost_limit'),
        (('unknown_model_price','mangler pris'), 'unknown_price'),
        (('source_identity','identity mismatch','app identity','appversjon'), 'identity'),
        (('permission','another device','another app','tilhører'), 'scope'),
        (('expired','utløpt'), 'expired'),
        (('401','invalid_api_key','authenticationerror','api key'), 'api_key'),
        (('insufficient_quota','billing','credit_balance_exhausted'), 'api_account'),
        (('429','ratelimit','rate limit'), 'ai_busy'),
        (('no_speech','ingen forståelig','ingen tale'), 'no_speech'),
        (('upload_missing','opptaket kom ikke'), 'audio_missing'),
        (('audio_error','audio_playback_failed','speech_failed'), 'audio_failed'),
        (('command_timeout','timeout','timed out','tidsgrens'), 'timeout'),
        (('cancelled','canceled','avbrutt'), 'cancelled'),
        (('connection','network','connecterror','nettverk'), 'network'),
        (('disk limit','workspace disk','disk full'), 'disk_full'),
        (('storage_unavailable','sd-kort','sd removed','sd unavailable'), 'storage'),
        (('capability','capabilities','firmware','absent from actual device'), 'firmware'),
        (('pre-delivery','release profile','budget','syntax','coverage missing','luaerror'), 'test_failed'),
        (('busy','opptatt'), 'busy'),
        (('run_rejected','run_failed'), 'run_failed'),
        (('invalid_event','invalid event','schema'), 'invalid_event'),
    )
    return TEXT[next((key for needles,key in choices if any(n in text for n in needles)),'failed')]


def build_text(phase,*,operation='new',attempt=1,total=4,progress=0,detail='',delivery=False):
    if phase=='generating':
        key=operation if operation in {'new','update','repair'} else 'new'
        total=total if type(total) is int and 1<=total<=4 else 4
        attempt=attempt if type(attempt) is int and 1<=attempt<=total else 1
        return checked(f'{TEXT[key]} ({attempt}/{total})')
    if phase=='testing' and progress>=75:return TEXT['review']
    if phase=='ready':return TEXT['sending' if delivery else 'ready']
    if phase=='failed':return error_text(detail)
    return TEXT.get(phase,TEXT['unknown'])


def repair_text(job):
    status=job.get('status')
    if status=='ready':return TEXT['repair_ready']
    if status=='awaiting_confirmation':return TEXT['prepared']
    if status=='failed':return error_text(job.get('message',''))
    if status in {'queued','interrupted','unavailable','not_found'}:return TEXT[status]
    if status=='building':
        return build_text(job.get('phase','preparing'),operation='repair',attempt=job.get('attempt',1),total=job.get('total',4),progress=job.get('progress',0))
    return TEXT['unknown']


def display_event(event,*,operation='new',delivery=False):
    """Only status fields change. Assistant replies, transcripts and TTS do not."""
    event=dict(event)
    kind=event.get('type')
    if kind in {'error','audio_error','input_retry'}:
        detail=event.get('message','')
        event.setdefault('diagnostic_message',detail)
        event['message']=event['status_message']=error_text(detail,event.get('code',''))
        event['status_text_version']=VERSION
    elif kind=='build_progress':
        event['message']=build_text(event.get('phase'),operation=operation,attempt=event.get('attempt',1),
                                    total=event.get('total',4),progress=event.get('progress',0),detail=event.get('message',''),delivery=delivery)
        event['status_text_version']=VERSION
    elif kind=='session_snapshot' and event.get('progress'):
        event['progress']=display_event({**event['progress'],'type':'build_progress'},operation=operation,delivery=delivery)
    return event
