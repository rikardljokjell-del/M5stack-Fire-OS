import pytest
from fire_backend.models import AppTestSequence
from fire_backend.api_registry import preview_capabilities
from fire_backend.builds import validate_release
from fire_backend.service import Backend
from test_device_protocol import configured

SOURCE='''local menu=true local job=nil
function init() end
function on_button(b,a)
 if b~='B' then menu=true return end
 if b=='B' then
  if menu then menu=false else job=fire.i2c.scan(0) end
 end
end
function update(dt)
 if job then local s=fire.jobs.poll(job) if s.done then fire.jobs.result(job) fire.jobs.close(job) job=nil end end
 fire.display.text(4,4,menu and 'Menu' or 'I2C',2016)
end'''


async def test_toolbox_test_plan_must_start_operation_not_only_enter_page(tmp_path):
    b=Backend(configured(tmp_path))
    try:
        app=dict(main_lua=SOURCE,required_services=['display','buttons','i2c','jobs'],api_version='fire-lua-0.2',
            hardware=preview_capabilities()['hardware'],max_memory=131072,max_runtime_ms=5000,require_io_coverage=True)
        with pytest.raises(ValueError,match='coverage missing for i2c'):await validate_release(app,b.store,'build-no-io')
        result=await validate_release({**app,'test_sequences':[dict(name='scan',buttons=['B','B'],interval_ms=100)]},b.store,'build-io')
        assert result['jobs_started']['i2c.scan']>=4
        assert result['io_calls']['jobs.close']>=4
        assert {p['profile'] for p in result['profiles'] if p.get('scenario')=='scan'}=={'idle','io_error','io_timeout','io_disconnect'}
        assert result['physical_verified'] is False
    finally:await b.close()


@pytest.mark.parametrize('change',[{'buttons':['X']},{'buttons':['B']*33},{'interval_ms':True},{'interval_ms':10}])
def test_scenario_is_bounded_and_cannot_supply_code(change):
    with pytest.raises(ValueError):AppTestSequence.model_validate({'name':'scan','buttons':['B'],**change})


def test_default_build_budget_covers_generation_review_and_corrections(tmp_path):
    s=configured(tmp_path)
    assert s.fire_build_timeout_seconds>=8*s.fire_ai_timeout_seconds
