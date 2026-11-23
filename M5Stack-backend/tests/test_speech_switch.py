import asyncio
from unittest.mock import Mock

import pytest

from fire_backend.ai import MockProvider,OpenAIProvider
from fire_backend.audio import AudioManager
from fire_backend.capabilities import policy,status
from fire_backend.models import State
from fire_backend.service import Backend
from test_audio import wav_data
from test_device_protocol import configured
from test_repair_target import session


class SpeechCounter(MockProvider):
    def __init__(self):self.speech_calls=0;self.transcribe_calls=0
    async def speech(self,text):
        self.speech_calls+=1
        async for chunk in super().speech(text):yield chunk
    async def transcribe(self,data):
        self.transcribe_calls+=1
        return await super().transcribe(data)


async def test_speech_off_keeps_mic_transcription_dialog_and_build_proposal_with_no_audio_request(tmp_path):
    p=SpeechCounter();b=Backend(configured(tmp_path,fire_audio_enabled=True,fire_speech_enabled=False),p)
    b.audio=AudioManager(b)
    try:
        s,peer=await session(b);s.turn_id='turn-muted'
        audio=policy(b.settings,'device',s.capabilities)['conversation_audio']
        assert audio['input_enabled'] and audio['output_announced'] and not audio['output_enabled']
        assert status(b.settings,s)['code']=='backend_speech_disabled'
        path=b.store.path('audio','audio-input-muted','.wav');path.write_bytes(wav_data())
        item={'id':'audio-input-muted','session_id':s.id,'device_id':s.device_id,'turn_id':s.turn_id,'status':'uploaded'}
        await b.audio.transcribe(s,item,path)
        if s.speech_task:await s.speech_task
        assert p.transcribe_calls==1 and p.speech_calls==0
        assert s.state==State.awaiting_build_confirmation and s.proposal_id
        assert any(e['type']=='assistant_message' for e in peer.events)
        assert not any(e['type'] in {'audio_ready','audio_error'} for e in peer.events)
        assert s.audio_status['phase']=='text_ready'
        await b.confirm_build(s,s.proposal_id);await asyncio.wait_for(s.task,10)
        assert b.store.get('builds',s.build_id)['status']=='ready'
        assert not any(c['kind']=='run' for c in b.store.list('commands'))
    finally:await b.close()


async def test_provider_speech_off_cannot_create_a_paid_connection_even_when_called_directly(tmp_path):
    p=OpenAIProvider(configured(tmp_path,fire_speech_enabled=False))
    p.api=Mock(side_effect=AssertionError('No paid speech request allowed'))
    assert [chunk async for chunk in p.speech('Hei')]==[]
    p.api.assert_not_called()
