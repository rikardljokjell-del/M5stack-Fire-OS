local x = 24
local direction = 1
function init()
  fire.display.clear(0)
end
function update(dt_ms)
  x = x + direction * dt_ms * 0.08
  if x >= 296 then x = 296; direction = -1 end
  if x <= 24 then x = 24; direction = 1 end
  fire.display.clear(0)
  fire.display.circle(math.floor(x), 120, 20, 2016)
end
