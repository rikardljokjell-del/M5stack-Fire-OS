local elapsed = 0
function init()
  for i = 0, 9 do fire.rgb.set(i, 0, 0, 0) end
end
function update(dt_ms)
  elapsed = elapsed + dt_ms
  local red = math.floor((math.sin(elapsed / 500) + 1) * 127)
  local blue = 254 - red
  for i = 0, 9 do
    fire.rgb.set(i, red, 0, blue)
  end
end
