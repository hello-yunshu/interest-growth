import io,json,pytest

from interest_growth_native.llm import OpenAICompatibleClient
from interest_growth_native.web_tools import validate_public_https
from interest_growth_native.errors import ValidationError

def test_tool_argument_array_and_malformed_json_decode_fail_closed():
    c=OpenAICompatibleClient(base_url="https://example.com",api_key="x",model="m")
    assert c._decode_args("[1,2]")=={"value":[1,2]}
    assert c._decode_args("{bad")=={"raw":"{bad"}

def test_finish_reason_length_continues_with_strict_bound():
    c=OpenAICompatibleClient(base_url="https://example.com",api_key="x",model="m",max_continuations=1)
    calls=[]
    def fake(payload):
        calls.append(payload)
        if len(calls)==1:
            return {"choices":[{"message":{"content":"A"},"finish_reason":"length"}],"usage":{"total_tokens":2}}
        return {"choices":[{"message":{"content":"B"},"finish_reason":"stop"}],"usage":{"total_tokens":3}}
    c._request_json=fake
    out=c.complete(messages=[{"role":"user","content":"x"}])
    assert out.text=="AB"
    assert len(calls)==2
    assert out.usage["total_tokens"]==5

class FakeResp:
    def __init__(self,lines):self.lines=[x.encode() for x in lines]
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def __iter__(self):return iter(self.lines)

def test_openai_stream_without_tools_is_true_answer_delta():
    c=OpenAICompatibleClient(base_url="https://example.com",api_key="x",model="m")
    c._open_stream=lambda payload:FakeResp([
        'data: '+json.dumps({"choices":[{"delta":{"content":"A"},"finish_reason":None}]})+'\n',
        'data: '+json.dumps({"choices":[{"delta":{"content":"B"},"finish_reason":"stop"}]})+'\n',
        'data: [DONE]\n',
    ])
    ev=list(c.stream(messages=[{"role":"user","content":"x"}],tools=None))
    assert [x.text for x in ev if x.type=="answer_delta"]==["A","B"]

def test_openai_stream_with_tool_buffers_content_as_narration_not_answer():
    c=OpenAICompatibleClient(base_url="https://example.com",api_key="x",model="m")
    c._open_stream=lambda payload:FakeResp([
        'data: '+json.dumps({"choices":[{"delta":{"content":"checking"},"finish_reason":None}]})+'\n',
        'data: '+json.dumps({"choices":[{"delta":{"tool_calls":[{"index":0,"id":"c1","function":{"name":"reason","arguments":"{}"}}]},"finish_reason":"tool_calls"}]})+'\n',
        'data: [DONE]\n',
    ])
    ev=list(c.stream(messages=[{"role":"user","content":"x"}],tools=[{"type":"function"}]))
    assert [x.text for x in ev if x.type=="narration_delta"]==["checking"]
    assert not [x for x in ev if x.type=="answer_delta"]
    call=next(x.tool_call for x in ev if x.type=="tool_call")
    assert call["name"]=="reason" and call["arguments"]=={}

def test_web_url_guard_rejects_http_and_loopback():
    with pytest.raises(ValidationError):validate_public_https("http://example.com")
    with pytest.raises(ValidationError):validate_public_https("https://127.0.0.1/private")
