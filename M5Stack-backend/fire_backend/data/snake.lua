local snake = {{x=10,y=7},{x=9,y=7},{x=8,y=7}}
local dx, dy = 1, 0
local food = {x=14,y=7}
local elapsed = 0
local alive = true
function init()
  fire.display.clear(0)
end
function on_button(button, action)
  if action ~= "pressed" then return end
  if button == "A" then dx,dy = dy,-dx end
  if button == "C" then dx,dy = -dy,dx end
end
function update(dt_ms)
  elapsed = elapsed + dt_ms
  if not alive then
    fire.display.text(80,110,"Game over",65535)
    return
  end
  if elapsed < 160 then return end
  elapsed = 0
  local head = {x=(snake[1].x+dx)%20,y=(snake[1].y+dy)%15}
  local eat = head.x==food.x and head.y==food.y
  local length = #snake
  local collision_limit = length - 1
  if eat then collision_limit = length end
  for i=1,collision_limit do
    if snake[i].x==head.x and snake[i].y==head.y then alive=false; return end
  end
  if eat then
    length = math.min(60,length+1)
    food = {x=(food.x+7)%20,y=(food.y+3)%15}
  end
  for i=length,2,-1 do snake[i]=snake[i-1] end
  snake[1]=head
  fire.display.clear(0)
  for i=1,length do fire.display.rect(snake[i].x*16,snake[i].y*16,14,14,2016) end
  fire.display.rect(food.x*16,food.y*16,14,14,63488)
end
