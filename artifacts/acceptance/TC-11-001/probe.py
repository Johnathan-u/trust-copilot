"""TC-11-001 baseline probe: fakes only, --network none. Shows how failures collapse on a given tree."""
from types import SimpleNamespace
import openai
try:
    import httpx2 as hx
except ImportError:
    import httpx as hx
from app.services import answer_generation as ag
ag.time.sleep = lambda *_: None
REQ = hx.Request("POST", "https://provider.invalid/v1/chat/completions")
def st(cls, s):
    return cls(f"Error code: {s} - SYNTH-SECRET", response=hx.Response(s, request=REQ, json={}), body={})
def comp(content=None, refusal=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content, refusal=refusal), finish_reason="stop")])
class C:
    def __init__(s, item): s.item=item; s.calls=0; s.chat=SimpleNamespace(completions=SimpleNamespace(create=s.c))
    def c(s, **k):
        s.calls+=1
        if isinstance(s.item, BaseException): raise s.item
        return s.item
EV=[{"id":1,"text":"Synthetic: quarterly access reviews.","metadata":{"filename":"s.docx"},"score":0.8}]
cases = {
 "grounded": (C(comp("Yes. Quarterly access reviews.")), EV),
 "no_evidence": (C(comp("x")), []),
 "refusal": (C(comp(None, refusal="I can't help with that.")), EV),
 "malformed": (C(comp('{"a":1}')), EV),
 "model_unavailable_404": (C(st(openai.NotFoundError, 404)), EV),
 "credentials_401": (C(st(openai.AuthenticationError, 401)), EV),
}
for name, (cl, ev) in cases.items():
    try:
        r = ag._generate_single_question_answer(SimpleNamespace(id=1, text="Q?"), ev, 1, 1, "m", 0.2, "s", cl)
        outcome = getattr(r, "outcome", None)
        print(f"{name:24s} status={r[4]!r:24s} text={r[1]!r:28.28s} outcome={getattr(outcome,'value',outcome)} calls={cl.calls}")
    except Exception as e:
        print(f"{name:24s} RAISED {type(e).__name__}: code={getattr(getattr(e,'code',None),'value',None)} msg={str(e)[:70]!r} calls={cl.calls}")
