from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request


def gemini_generate_text(*, model: str, prompt: str, api_key: str) -> str:
    """Gemini API を呼び出して、生成テキスト（文字列）を返す（429 は簡易リトライ）。"""
    # 事前条件: APIキーが無い場合は早期に失敗させる（後段のHTTPエラーより分かりやすい）
    if not (api_key or "").strip():
        raise RuntimeError("Gemini APIキーが未設定です（.logiclint/secret.json を用意してください）")

    # リクエストURL（model名とAPIキーはURLエンコードして埋め込む）
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib.parse.quote(model, safe='')}:generateContent"
        f"?key={urllib.parse.quote(api_key, safe='')}"
    )

    # 送信するJSON（promptは text パートとして渡す）
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    # HTTPリクエストを組み立てる（UTF-8 JSONとしてPOST）
    req = urllib.request.Request(
        url=url,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    # 送信・受信（429は短い待ちで最大3回まで簡易リトライ）
    raw: bytes | None = None
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            # 成功時: レスポンスボディ（bytes）を受け取る
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
            last_err = None
            break
        except urllib.error.HTTPError as e:
            # HTTPレベルの失敗（エラーボディが取れる場合はそれも保持する）
            body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
            last_err = RuntimeError(f"Gemini API HTTPError: {e.code} {e.reason}\n{body}")

            if e.code == 429 and attempt < 4:
                # 429（クォータ/レート制限）: 可能なら RetryInfo の delay を読んで待つ
                retry_seconds: float | None = None
                try:
                    err_obj = json.loads(body)
                    details = (((err_obj.get("error") or {}).get("details")) or [])
                    for d in details:
                        if isinstance(d, dict) and d.get("@type") == "type.googleapis.com/google.rpc.RetryInfo":
                            delay = str(d.get("retryDelay") or "").strip()
                            m = re.match(r"^(\d+)(?:\.\d+)?s$", delay)
                            if m:
                                retry_seconds = float(m.group(1))
                except Exception:
                    retry_seconds = None

                # RetryInfo が無い場合は指数バックオフっぽく増やす
                if retry_seconds is None:
                    retry_seconds = 2.0 * attempt
                time.sleep(retry_seconds)
                continue

            # 429以外はそのまま失敗（last_errでまとめて投げる）
            break
        except Exception as e:
            # 通信/タイムアウト等のその他エラー
            last_err = RuntimeError(f"Gemini API 呼び出しに失敗しました: {e}")
            break

    # 最終的に失敗していれば、原因（last_err）を投げる
    if last_err is not None:
        raise last_err
    if raw is None:
        raise RuntimeError("Gemini API 応答が空です")

    # レスポンスJSONを解析して candidates[0].content.parts[*].text を連結する
    obj = json.loads(raw.decode("utf-8"))
    cands = obj.get("candidates") or []
    if not cands:
        raise RuntimeError(f"Gemini API 応答に candidates がありません: {obj}")
    content = (cands[0] or {}).get("content") or {}
    parts = content.get("parts") or []
    texts = []
    for p in parts:
        if isinstance(p, dict) and "text" in p:
            texts.append(str(p["text"]))
    out = "".join(texts).strip()
    if not out:
        raise RuntimeError(f"Gemini API 応答に text がありません: {obj}")
    return out

