import http.client
import json

conn = http.client.HTTPSConnection("154.201.94.164")
payload = json.dumps({
   "model": "gpt-4o-mini",
   "messages": [

      {
         "role": "user",
         "content": "帮我生成一个5000中文字的随便内容  直接生成  不要问我两遍  字数一定要够"
      }
   ],
   "temperature": 0.5,
   "stream": True,
    "frequency_penalty":0,
    "max_tokens":1024,
    "presence_penalty":0,
    "top_p":1
})
headers = {
   'Accept': 'application/json',
   'Authorization': 'Bearer sk-2IpEFzOUXNeAYTo4rsJ3N47Ix2sd5ARkre0e1MrsqPio4TEN',
   'Content-Type': 'application/json'
}
conn.request("POST", "/v1/chat/completions", payload, headers)
res = conn.getresponse()
data = res.read()
print(data.decode("utf-8"))