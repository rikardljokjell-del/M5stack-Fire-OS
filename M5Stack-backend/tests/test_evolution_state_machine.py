"""Exercise the actual durable control methods, not a shadow transition model."""
import asyncio
import tempfile
from pathlib import Path
from hypothesis import settings
from hypothesis.stateful import RuleBasedStateMachine,rule,invariant

from fire_backend.service import Backend
from fire_backend.evolution_models import EvolutionConfig
from fire_backend.evolution import ACTIVE
from test_device_protocol import configured,CAPS


class Controls(RuleBasedStateMachine):
    def __init__(self):
        super().__init__();self.directory=tempfile.TemporaryDirectory();self.runner=asyncio.Runner()
        self.backend=Backend(configured(Path(self.directory.name)))
        self.project=self.backend.new_project('fire-01','device')
        self.backend.store.put('devices','fire-01',{'id':'fire-01','capabilities':CAPS})
        self.proposal=None;self.jobs=[]

    def run(self,awaitable):return self.runner.run(awaitable)
    @rule()
    def configure(self):
        engine=self.backend.evolution;revision=engine.state('fire-01',self.project['id'])['revision']
        config=EvolutionConfig(enabled=True,flags={'generate':True},autonomy='manual').model_dump()
        p=self.run(engine.prepare('fire-01',self.project['id'],'configure',config,revision))
        self.run(engine.confirm('fire-01',self.project['id'],p['id'],revision))

    @rule()
    def prepare(self):
        engine=self.backend.evolution;state=engine.state('fire-01',self.project['id'])
        if state['config']['enabled']:
            self.proposal=self.run(engine.prepare('fire-01',self.project['id'],'generate',{'goal':'Tell med knapp'},state['revision']))

    @rule()
    def confirm_twice(self):
        if not self.proposal:return
        e=self.backend.evolution;p=self.proposal
        try:
            result=self.run(e.confirm('fire-01',self.project['id'],p['id'],p['expected_revision']))
            again=self.run(e.confirm('fire-01',self.project['id'],p['id'],p['expected_revision']))
            assert result==again
            if result.get('job_id') not in self.jobs:self.jobs.append(result['job_id'])
            self.run(asyncio.sleep(0))
        except ValueError:pass  # Stale or another active job; no silent new mandate.

    @rule()
    def pause(self):self.control('pause')
    @rule()
    def resume(self):self.control('resume')
    @rule()
    def stop(self):self.control('stop')
    @rule()
    def restart(self):
        self.run(self.backend.close())
        self.backend=Backend(configured(Path(self.directory.name)))
        self.run(asyncio.sleep(0))
        assert not self.backend.evolution.tasks  # No automatic replay after restart.

    @rule()
    def lost_confirm_reply_and_stale_retry(self):
        if not self.proposal:return
        p=self.proposal;e=self.backend.evolution
        before=len(self.backend.store.list('evolution_mandates'))
        try:
            self.run(e.confirm('fire-01',self.project['id'],p['id'],p['expected_revision']))  # Reply is lost.
            after=len(self.backend.store.list('evolution_mandates'))
            self.run(e.confirm('fire-01',self.project['id'],p['id'],p['expected_revision']))
            assert len(self.backend.store.list('evolution_mandates'))==after and after<=before+1
        except ValueError:pass
    def control(self,action):
        if not self.jobs:return
        e=self.backend.evolution;revision=e.state('fire-01',self.project['id'])['revision']
        try:self.run(e.control('fire-01',self.project['id'],action,revision,job_id=self.jobs[-1]))
        except ValueError:pass

    @invariant()
    def one_active_app_and_no_implicit_build_or_run(self):
        rows=self.backend.store.list('evolution_jobs')
        assert sum(r['state'] in ACTIVE|{'awaiting_build_confirm'} for r in rows)<=1
        assert not self.backend.store.list('builds') and not self.backend.store.list('commands')
        assert not self.backend.usage.records()

    def teardown(self):
        self.run(self.backend.close());self.runner.close();self.directory.cleanup()


TestControls=Controls.TestCase
TestControls.settings=settings(max_examples=8,stateful_step_count=16,deadline=None)
