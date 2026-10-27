"""TC-11-001 baseline probe: fakes only, --network none.

Shows how failures collapse on a given tree.
"""

from types import SimpleNamespace

import openai

try:
    import httpx2 as hx
except ImportError:
    import httpx as hx

from app.services import answer_generation as ag

ag.time.sleep = lambda *_: None
REQ = hx.Request("POST", "https://provider.invalid/v1/chat/completions")


def st(cls, status):
    return cls(
        f"Error code: {status} - SYNTH-SECRET",
        response=hx.Response(status, request=REQ, json={}),
        body={},
    )


def comp(content=None, refusal=None):
    message = SimpleNamespace(content=content, refusal=refusal)
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(choices=[choice])


class C:
    def __init__(self, item):
        self.item = item
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.c))

    def c(self, **_k):
        self.calls += 1
        if isinstance(self.item, BaseException):
            raise self.item
        return self.item


EV = [
    {
        "id": 1,
        "text": "Synthetic: quarterly access reviews.",
        "metadata": {"filename": "s.docx"},
        "score": 0.8,
    }
]
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
        question = SimpleNamespace(id=1, text="Q?")
        result = ag._generate_single_question_answer(question, ev, 1, 1, "m", 0.2, "s", cl)
        outcome = getattr(result, "outcome", None)
        outcome_value = getattr(outcome, "value", outcome)
        print(
            f"{name:24s} status={result[4]!r:24s} text={result[1]!r:28.28s} "
            f"outcome={outcome_value} calls={cl.calls}"
        )
    except Exception as exc:
        code = getattr(getattr(exc, "code", None), "value", None)
        print(
            f"{name:24s} RAISED {type(exc).__name__}: code={code} "
            f"msg={str(exc)[:70]!r} calls={cl.calls}"
        )
