-- Offline API example. All PC readings are simulated; firmware owns real I/O.
local mode, job, status, opened = 1,nil,'B start  C stop',false
local titles={'I2C scan','GPIO test','PWM test','UART terminal'}
local function stop()
  if job then fire.jobs.cancel(job);fire.jobs.close(job);job=nil end
  fire.gpio.release(26);fire.pwm.stop(26);fire.uart.close(2)
  opened=false
end
function init() end
function on_button(button,action)
  if action~='pressed' then return end
  if button=='A' then stop();mode=mode%4+1;status='B start  C stop'
  elseif button=='C' then stop();status='Stopped'
  elseif button=='B' and not job then
    local err=nil
    if mode==1 then job,err=fire.i2c.scan(0)
    elseif mode==2 then
      local ok;ok,err=fire.gpio.mode(26,'output')
      if ok then ok,err=fire.gpio.write(26,1) end
      if ok then status='GPIO 26 HIGH' end
    elseif mode==3 then
      local ok;ok,err=fire.pwm.configure(26,1000,8)
      if ok then ok,err=fire.pwm.write(26,128) end
      if ok then status='PWM 1kHz 50%' end
    else
      if not opened then opened,err=fire.uart.open(2,9600,36,26,'8N1') end
      if opened then job,err=fire.uart.read(2,64) end
    end
    if err then status=tostring(err) elseif job then status='Working' end
  end
end
function update(dt)
  if job then
    local state=fire.jobs.poll(job)
    if state.done then
      local result=fire.jobs.result(job)
      if not result.ok then status=result.error_code
      elseif mode==1 then status='Found '..tostring(#result.addresses)..' addresses'
      else status='UART received '..tostring(#result.bytes)..' bytes' end
      fire.jobs.close(job);job=nil
    end
  end
  fire.display.text(8,8,'Electronics toolbox',65535)
  fire.display.text(8,32,titles[mode],2016)
  fire.display.text(8,60,status,65535)
  fire.display.text(8,216,'A next  B start  C stop',65535)
end
