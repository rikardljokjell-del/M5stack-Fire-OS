local x = 0
local previous_y = 120
function init()
  fire.display.clear(0)
end
function update(dt_ms)
  local accel = fire.imu.accel()
  local y = math.floor(math.max(1, math.min(238, 120 - accel.x * 80)))
  if x == 0 then fire.display.clear(0); previous_y = y end
  if x > 0 then fire.display.line(x - 1, previous_y, x, y, 2016) end
  previous_y = y
  x = (x + 1) % 320
end
