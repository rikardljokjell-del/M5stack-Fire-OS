import asyncio
import json
import unicodedata

import pytest

from fire_backend.status_text import TEXT,VERSION,checked,build_text,repair_text,error_text,display_event
from fire_backend.models import DeviceEvent,State
from fire_backend.protocol import dispatch
from fire_backend.service import Backend
from fire_backend.storage import new_id
from test_device_protocol import configured
from test_repair_target import session
from test_background_repairs import RepairProvider


def assert_line(text):
    assert text==unicodedata.normalize('NFC',text)
    assert 0<len(text)<=28 and len(text.encode('utf-8'))<=28
    assert not any(c in text for c in '\r\n\t…') and '...' not in text
    assert text.encode('utf-8')[:28].decode('utf-8')==text  # Existing byte cutoff cannot split it.


def test_catalog_all_build_modes_attempts_and_repair_states_are_complete_lines():
    for value in TEXT.values():assert_line(value)
    for mode in ('new','update','repair'):
        for attempt in range(1,5):
            for phase in ('preparing','generating','validating','compiling','testing','packaging','ready','failed','unknown'):
                for percent in (0,65,75,100):assert_line(build_text(phase,operation=mode,attempt=attempt,progress=percent,detail='x'*1000))
    for status in ('awaiting_confirmation','queued','building','ready','failed','interrupted','unavailable','not_found','unknown'):
        assert_line(repair_text(dict(status=status,phase='generating',message='Last ned og ...'+'x'*1000)))
    assert build_text('generating',operation='repair',attempt=3)=='Retter appen (3/4)'
    assert build_text('generating',attempt=6,total=6)=='Lager appen (6/6)'
    assert build_text('generating',attempt=8,total=None)=='Lager appen (8)'
    assert 'kjøring' in build_text('ready')


@pytest.mark.parametrize('bad',['Last ned og ...','Lang tekst '*9,'To\nlinjer','Sjekker\tappen','Klargj\u00f8r\u0061\u030a'])
def test_catalog_rejects_overlong_partial_or_broken_unicode_text(bad):
    with pytest.raises(ValueError):checked(bad)


def test_errors_have_short_status_and_preserve_diagnostic_separately():
    raw='Avslutt aktivt opptak, bygg eller kjøring før du velger app.\nDetaljer: '+ 'x'*200
    event=display_event({'type':'error','code':'event_rejected','message':raw})
    assert_line(event['message']);assert event['status_message']==event['message']
    assert event['diagnostic_message']==raw and event['status_text_version']==VERSION
    assert error_text('OpenAI HTTP401 AuthenticationError')==TEXT['api_key']
    assert error_text('OpenAI HTTP429 RateLimitError')==TEXT['ai_busy']
    assert error_text('Release profile idle: callback budget exceeded')==TEXT['test_failed']


def test_dialog_and_audio_content_are_not_status_text():
    spoken='Jeg lager et spill med tydelige figurer og tre knapper. Du kan endre både lyd og lys i menyen. Æ, ø og å beholdes.'
    for event in ({'type':'assistant_message','text':spoken},{'type':'transcript','text':spoken},
                  {'type':'audio_ready','text':spoken,'download_url':'/audio/example'}):
        assert display_event(event)==event
        assert json.loads(json.dumps(event,ensure_ascii=False))==event
    old={'type':'session_snapshot','progress':{'phase':'testing','progress':75,'message':'For lang historisk tekst '*9}}
    assert display_event(old)['progress']['message']==TEXT['review']


async def test_device_can_choose_new_app_while_confirmed_build_finishes_in_background(tmp_path):
    provider=RepairProvider();provider.release.clear();b=Backend(configured(tmp_path),provider)
    try:
        s,peer=await session(b);await b.text(s,'Lag en sirkel')
        build=await b.confirm_build(s,s.proposal_id);await provider.entered.wait()
        task=s.task;original=s.project_id
        choice=DeviceEvent(event='app_select',app_mode='new',device_id=s.device_id,protocol_version='0.2',
            event_id=new_id('evt'),session_id=s.id,boot_id=s.boot_id)
        await dispatch(b,s,choice)
        assert s.project_id!=original and s.state==State.idle and not task.done()
        provider.release.set();await asyncio.wait_for(task,10)
        assert b.store.get('builds',build['id'])['status']=='ready'
        assert b.store.get('projects',original)['latest_package']==build['id']
        assert not b.store.list('commands') and s.project_id!=original
        assert not any(e['type']=='install_request' for e in peer.events)
    finally:await b.close()


async def test_device_confirms_next_build_while_previous_build_is_busy(tmp_path):
    provider=RepairProvider();provider.release.clear();b=Backend(configured(tmp_path),provider)
    try:
        s,_=await session(b);await b.text(s,'Lag en sirkel')
        first=await b.confirm_build(s,s.proposal_id);await provider.entered.wait();first_task=s.task
        b.detach_device_build(s);await b.text(s,'Lag en sirkel')
        second=await b.confirm_build(s,s.proposal_id);second_task=s.task
        assert second['status']=='queued' and second['id']!=first['id']
        provider.release.set();await asyncio.wait_for(asyncio.gather(first_task,second_task),15)
        assert len(provider.calls)==2
        assert b.store.get('builds',first['id'])['status']==b.store.get('builds',second['id'])['status']=='ready'
        assert b.store.get('packages',second['id'])['manifest']['version']=='0.1.2'
        assert not b.build_lock.locked()
    finally:await b.close()


async def test_app_selection_cancels_old_recording_or_reply_instead_of_rejecting(tmp_path):
    b=Backend(configured(tmp_path))
    try:
        s,_=await session(b)
        s.turn_id='turn-old';s.state=State.processing;s.activity='speaking'
        s.input_task=asyncio.create_task(asyncio.sleep(10))
        action=DeviceEvent(event='app_select',app_mode='new',device_id=s.device_id,protocol_version='0.2',
            event_id=new_id('evt'),session_id=s.id,boot_id=s.boot_id)
        await dispatch(b,s,action)
        assert s.input_task.cancelled() and s.state==State.idle and s.activity=='idle'
        assert 'turn-old' in s.retired_turns
    finally:await b.close()
