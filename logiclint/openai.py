from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


def openai_generate_text(*, base_url: str, model: str, prompt: str, api_key: str) -> str:
    """OpenAI互換 API（Chat Completions）を呼び出して生成テキスト（文字列）を返す。

    - base_url 例: https://api.openai.com/v1
    - エンドポイント: {base_url}/chat/completions
    """
    if not (api_key or "").strip():
        raise RuntimeError("OpenAI APIキーが未設定です（.logiclint/secret.json を用意してください）")

    base = (base_url or "").strip().rstrip("/")
    if not base:
        base = "https://api.openai.com/v1"
    url = f"{base}/chat/completions"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url=url,
        data=data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {api_key.strip()}",
        },
        method="POST",
    )

    raw: bytes | None = None
    last_err: Exception | None = None

    # 429/5xx を中心に簡易リトライ（最大3回）
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
            last_err = None
            break
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
            last_err = RuntimeError(f"OpenAI API HTTPError: {e.code} {e.reason}\n{body}")

            # retry on 429 or transient 5xx
            if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                time.sleep(2.0 * attempt)
                continue
            break
        except Exception as e:
            last_err = RuntimeError(f"OpenAI API 呼び出しに失敗しました: {e}")
            break

    if last_err is not None:
        raise last_err
    if raw is None:
        raise RuntimeError("OpenAI API 応答が空です")

    obj = json.loads(raw.decode("utf-8"))
    choices = obj.get("choices") or []
    if not choices:
        raise RuntimeError(f"OpenAI API 応答に choices がありません: {obj}")

    msg = (choices[0] or {}).get("message") or {}
    content = msg.get("content")

    # OpenAI互換実装の中には content が list で返るものがあるため吸収する
    if isinstance(content, list):
        texts = []
        for it in content:
            if isinstance(it, dict) and "text" in it:
                texts.append(str(it["text"]))
            elif isinstance(it, str):
                texts.append(it)
        out = "".join(texts).strip()
    else:
        out = str(content or "").strip()

    if not out:
        raise RuntimeError(f"OpenAI API 応答に message.content がありません: {obj}")
    return out

