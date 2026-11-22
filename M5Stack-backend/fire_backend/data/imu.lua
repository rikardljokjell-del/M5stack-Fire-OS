local samples = {}
local elapsed = 0
function init()
  fire.display.clear(0)
  for i=1,20 do samples[i]=120 end
end
function update(dt_ms)
  elapsed = elapsed + dt_ms
  if elapsed >= 100 then
    elapsed = elapsed % 100
    local accel = fire.imu.accel()
    for i=1,19 do samples[i]=samples[i+1] end
    samples[20]=math.floor(math.max(24, math.min(220, 120-accel.x*80)))
  end
  fire.display.text(16,8,"Helning",65535)
  for i=2,20 do fire.display.line((i-2)*16,samples[i-1],(i-1)*16,samples[i],2016) end
end
