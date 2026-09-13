"""The one model call in the audit: does a focus-order difference matter?

W&B Inference, `meta-llama/Llama-3.3-70B-Instruct`, pinned. Measured against
generally available models on four fixtures: 4/4 correct at 0.40s warm and
1,299 tokens, against 19-30s and three to six times the tokens for the
reasoning models, which were no more accurate. `Qwen/Qwen3-30B-A3B-Instruct-2507`
is deprecated in W&B's docs; do not use it.

Two things this file will not let you get wrong:

  * **`max_tokens` is at least 1000.** A 400-token cap truncates a reasoning
    model mid-object and reads as model failure. That produced one wrong
    conclusion already.
  * **The union is prompt-enforced, not schema-enforced.** With
    `required: ["status"]`, `{"status": "failed", "reason": "..."}` is
    schema-valid and useless. Every model returned exactly that until the
    prompt demanded `evidence_refs` explicitly. The caller still verifies each
    ref resolves; that check is deterministic code and does most of the work.
"""

from __future__ import annotations

import os
import json

MODEL = "meta-llama/Llama-3.3-70B-Instruct"
MAX_TOKENS = 1200

SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["passed", "failed", "not_evaluated"]},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
        "summary": {"type": "string"},
    },
    "required": ["status"],
    "additionalProperties": False,
}

PROMPT = """You judge WCAG 2.4.3 Focus Order on one page state.

Below are the elements the keyboard reached, in the order Tab reached them, and
the order a sighted person would read them, derived from their positions on the
page. Positions are document coordinates in CSS pixels.

A difference between the two orders is not automatically a failure. Decide
whether this particular difference would disadvantage someone using a keyboard.

Reply as JSON only.
  matches, or the difference is harmless -> {"status": "passed", "summary": "..."}
  the difference disadvantages a keyboard user ->
      {"status": "failed", "evidence_refs": ["stop 3", "stop 5"], "summary": "..."}
  you cannot tell from this evidence ->
      {"status": "not_evaluated", "reason": "..."}

evidence_refs is REQUIRED on a failed verdict. Each entry names a stop from the
list below, written exactly as "stop N", and must be one of the stops where the
order actually goes wrong. Do not use reason on a failed verdict.

State: __STATE__

Tab order reached these stops, in this order:
__TAB_ROWS__

Reading order derived from position would be:
__READING_ROWS__
"""


def _client():
    from openai import OpenAI

    entity = os.environ["WANDB_ENTITY"]
    project = os.environ.get("WANDB_PROJECT", "ally")
    # openai 3.x no longer takes project= the way 1.x did. The documented
    # fallback is the header, and setting it as a default means every call
    # carries it rather than each call site remembering.
    return OpenAI(base_url="https://api.inference.wandb.ai/v1",
                  api_key=os.environ["WANDB_API_KEY"],
                  default_headers={"OpenAI-Project": f"{entity}/{project}"})


def make_judge(client=None, model: str = MODEL):
    """Return a judge callable for `checks.check_focus_order`.

    Built once per run so the OpenAI client is constructed after weave.init;
    calls made through a client created before init are not captured.
    """
    client = client or _client()

    def judge(rec, tab_order, expected) -> dict | None:
        by_index = {s.index: s for s in rec.stops}

        def rows(order):
            out = []
            for i in order:
                s = by_index.get(i)
                if s is None:
                    continue
                out.append(f"  stop {i}: <{s.tag.lower()}> "
                           f"{(s.name or '(no accessible name)')[:44]!r} "
                           f"at x={s.x} y={s.y}")
            return "\n".join(out)

        # replace, not .format(): the prompt shows JSON objects and str.format
        # reads their braces as fields.
        prompt = (PROMPT.replace("__STATE__", rec.state)
                        .replace("__TAB_ROWS__", rows(tab_order))
                        .replace("__READING_ROWS__", rows(expected)))
        try:
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "FocusOrder", "schema": SCHEMA}},
                max_tokens=MAX_TOKENS,
            )
            return json.loads((r.choices[0].message.content or "").strip())
        except Exception as exc:
            # A judge that cannot answer must say so, not guess. The check turns
            # this into not_evaluated with the reason attached.
            return {"status": "not_evaluated",
                    "reason": f"the focus-order judge failed: {type(exc).__name__}: "
                              f"{str(exc)[:120]}"}

    return judge
