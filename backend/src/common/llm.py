"""Claude API 호출 (웹 검색 서버 도구 포함)."""
import json
import re

from . import config


def _client():
    import anthropic

    return anthropic.Anthropic(api_key=config.secret("ANTHROPIC_API_KEY"), timeout=600)


def extract_json(text: str):
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("{"): text.rfind("}") + 1]
    return json.loads(raw)


def ask_json(system: str, prompt: str, search: bool = False, max_uses: int = 12, max_tokens: int = 12000) -> dict:
    tools = [{"type": config.WEB_SEARCH_TOOL, "name": "web_search", "max_uses": max_uses,
              "user_location": {"type": "approximate", "country": "KR", "timezone": "Asia/Seoul"}}] if search else None
    messages = [{"role": "user", "content": prompt}]
    last_err = None
    for _ in range(2):
        kwargs = {"model": config.CLAUDE_MODEL, "max_tokens": max_tokens, "system": system, "messages": messages}
        if tools:
            kwargs["tools"] = tools
        resp = _client().messages.create(**kwargs)
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        try:
            return extract_json(text)
        except (ValueError, json.JSONDecodeError) as e:
            last_err = e
            messages = messages + [{"role": "assistant", "content": text or "(빈 응답)"},
                                   {"role": "user", "content": "위 결과를 지정한 JSON 형식 하나로만 다시 출력해 주세요."}]
            tools = None
    raise RuntimeError(f"Claude 응답을 JSON으로 해석하지 못했습니다: {last_err}")
