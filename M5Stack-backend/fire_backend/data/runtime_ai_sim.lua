-- Trusted private parser/fixture. Never exported as a general app JSON API.
local runtime_data_decode
local runtime_ai_parser=(function()
 local null={}
 local function decode(s,maxdepth,limits)
  local at,kinds=1,{}
  local function skip() while string.find(' \t\r\n',string.sub(s,at,at),1,true) and at<=#s do at=at+1 end end
  local function fail() error('invalid_json') end
  local function str()
   if string.sub(s,at,at)~='"' then fail() end
   at=at+1;local out={}
   while at<=#s do
    local c=string.sub(s,at,at);at=at+1
    if c=='"' then
     local text=table.concat(out)
     if #text>limits.json_string_bytes or not utf8.len(text) then fail() end
     return text
    end
    if c=='\\' then
     c=string.sub(s,at,at);at=at+1
     local escapes={['"']='"',['\\']='\\',['/']='/',['b']='\b',['f']='\f',['n']='\n',['r']='\r',['t']='\t'}
     if c=='u' then
      local hex=string.sub(s,at,at+3);if #hex~=4 or not string.match(hex,'^%x%x%x%x$') then fail() end
      local n=tonumber(hex,16);at=at+4
      if n>=0xD800 and n<=0xDBFF then
       if string.sub(s,at,at+1)~='\\u' then fail() end
       local low=tonumber(string.sub(s,at+2,at+5),16);if not low or low<0xDC00 or low>0xDFFF then fail() end
       n=0x10000+(n-0xD800)*1024+low-0xDC00;at=at+6
      elseif n>=0xDC00 and n<=0xDFFF then fail() end
      out[#out+1]=utf8.char(n)
     elseif escapes[c] then out[#out+1]=escapes[c] else fail() end
    else if string.byte(c)<32 then fail() end;out[#out+1]=c end
   end
   fail()
  end
  local value
  value=function(depth)
   if depth>maxdepth then fail() end;skip();local c=string.sub(s,at,at)
   if c=='"' then return str() end
   if c=='{' or c=='[' then
    local object=c=='{';local close=object and '}' or ']';at=at+1;skip();local t,seen={},{};local count=0;kinds[t]=object and 'object' or 'array'
    if string.sub(s,at,at)==close then at=at+1;return t end
    while true do
     skip();local key
     if object then key=str();skip();if string.sub(s,at,at)~=':' or seen[key] then fail() end;seen[key]=true;at=at+1 else key=count+1 end
     t[key]=value(depth+1);count=count+1
     if count>(object and limits.json_object_keys or limits.json_array_items) then fail() end
     skip();c=string.sub(s,at,at);at=at+1;if c==close then return t end;if c~=',' then fail() end
    end
   end
   for word,v in pairs({['true']=true,['false']=false,['null']=null}) do if string.sub(s,at,at+#word-1)==word then at=at+#word;return v end end
   local token=string.match(string.sub(s,at),'^-?%d+%.?%d*[eE]?[+-]?%d*')
   if not token or string.match(token,'^-?0%d') or string.match(token,'%.$') or string.match(token,'%.[eE]') then fail() end
   local n=tonumber(token);if not n or n~=n or math.abs(n)>3.4028234663852886e38 then fail() end;at=at+#token;return n
  end
  local result=value(1);skip();if at<=#s then fail() end;return result,kinds
 end
 local function schema(s,depth,limits,kinds)
  if kinds[s]~='object' or depth>limits.json_depth then error('invalid_schema') end
  local kind=s.type
  local fields={object={properties=true,required=true,additionalProperties=true},array={items=true,minItems=true,maxItems=true},string={minLength=true,maxLength=true},number={minimum=true,maximum=true},integer={minimum=true,maximum=true},boolean={},['null']={}}
  if not fields[kind] then error('invalid_schema') end
  for key in pairs(s) do if key~='type' and key~='description' and key~='enum' and not fields[kind][key] then error('invalid_schema') end end
  if s.description~=nil and (type(s.description)~='string' or #s.description>256) then error('invalid_schema') end
  for _,key in ipairs({'minimum','maximum','minItems','maxItems','minLength','maxLength'}) do
   local v=s[key];if v~=nil and (type(v)~='number' or v~=v or math.abs(v)>3.4028234663852886e38) then error('invalid_schema') end
   if v~=nil and key~='minimum' and key~='maximum' and (v%1~=0 or v<0) then error('invalid_schema') end
  end
  for _,pair in ipairs({{'minimum','maximum'},{'minItems','maxItems'},{'minLength','maxLength'}}) do
   if s[pair[1]] and s[pair[2]] and s[pair[1]]>s[pair[2]] then error('invalid_schema') end
  end
  if kind=='object' then
   if kinds[s.properties]~='object' or kinds[s.required]~='array' or s.additionalProperties~=false then error('invalid_schema') end
   local required={};for _,k in ipairs(s.required) do if type(k)~='string' or required[k] then error('invalid_schema') end;required[k]=true end
   local count=0;for key,child in pairs(s.properties) do if not required[key] then error('invalid_schema') end;count=count+1;schema(child,depth+1,limits,kinds) end
   if count~=#s.required then error('invalid_schema') end
  elseif kind=='array' then if type(s.maxItems)~='number' or s.maxItems>limits.json_array_items then error('invalid_schema') end;schema(s.items,depth+1,limits,kinds)
  elseif kind=='string' then if (not s.enum or s.maxLength) and (type(s.maxLength)~='number' or s.maxLength>limits.json_string_bytes) then error('invalid_schema') end end
  if s.enum then
   if kinds[s.enum]~='array' or #s.enum<1 or #s.enum>16 or kind=='object' or kind=='array' then error('invalid_schema') end
   for _,v in ipairs(s.enum) do
    if kind=='string' then
     if type(v)~='string' or utf8.len(v)<(s.minLength or 0) or utf8.len(v)>(s.maxLength or limits.json_string_bytes) then error('invalid_schema') end
    elseif kind=='number' or kind=='integer' then
     if type(v)~='number' or kind=='integer' and v%1~=0 or v<(s.minimum or -math.huge) or v>(s.maximum or math.huge) then error('invalid_schema') end
    elseif kind=='boolean' then if type(v)~='boolean' then error('invalid_schema') end
    elseif v~=null then error('invalid_schema') end
   end
  end
 end
 local function quoted_size(s)
  local n=2;for i=1,#s do local b=string.byte(s,i);n=n+(b<32 and 6 or (b==34 or b==92) and 2 or 1) end;return n
 end
 local function fixture(s)
  if s.type=='object' then local t,n,count={},2,0;for key,v in pairs(s.properties) do local x,size=fixture(v);t[key]=x;n=n+quoted_size(key)+1+size;count=count+1 end;return t,n+math.max(0,count-1) end
  if s.type=='array' then local t,n={},2;for i=1,(s.minItems or 0) do local x,size=fixture(s.items);t[i]=x;n=n+size end;return t,n+math.max(0,#t-1) end
  local v=s.enum and s.enum[1]
  if v==null or s.type=='null' then return nil,4 end
  if s.type=='string' then v=v or string.rep('x',math.max(s.minLength or 0,math.min(3,s.maxLength or 3)));return v,quoted_size(v) end
  if s.type=='boolean' then return v==true,v==true and 4 or 5 end
  v=v or math.max(s.minimum or 0,math.min(0,s.maximum or 0));if s.type=='integer' then v=math.ceil(v) end
  if s.maximum and v>s.maximum then error('invalid_schema') end;return v,#tostring(v)
 end
 runtime_data_decode=function(data,limits)
  local ok,value,kinds=pcall(decode,data,limits.json_depth,limits)
  if not ok or kinds[value]~='object' then return nil,'invalid_json' end
  return value
 end
 return function(data,spec,limits)
  local ok,d,dk=pcall(decode,data,limits.json_depth,limits);if not ok or dk[d]~='object' then return nil,'invalid_json' end
  local parsed,s,kinds=pcall(decode,spec,12,limits);if not parsed or kinds[s]~='object' or s.type~='object' then return nil,'invalid_schema' end
  local valid=pcall(schema,s,1,limits,kinds);if not valid then return nil,'invalid_schema' end
  local made,value,size=pcall(fixture,s);if not made then return nil,'invalid_schema' end
  return value,nil,size
 end
end)()
