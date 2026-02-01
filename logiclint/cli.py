from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .utils import (
    extract_json_text,
    force_utf8_stdio,
    get_api_key_from_file,
    normalize_user_path,
    read_json,
    read_text,
    write_json,
    write_text,
)
from .gemini import gemini_generate_text
from .prompting import build_prompt, load_default_assets
from .reporting import normalize_report, validate_report_shape


def iter_md_files(root: Path) -> list[Path]:
    """指定ディレクトリ配下の Markdown ファイルを収集し、安定順で返す。"""
    files = [p for p in root.rglob("*.md") if p.is_file()]
    files.sort(key=lambda p: str(p).lower())
    return files


def validate_config(
    cfg: dict[str, Any],
) -> tuple[Path, dict[str, Any], set[str], float, int, float]:
    """config の必須キーと型を検証し、実行に必要な値を取り出して返す。"""
    if not isinstance(cfg.get("output"), dict) or not str(cfg["output"].get("dir") or "").strip():
        raise SystemExit("ERROR: config.output.dir が必要です")
    if not isinstance(cfg.get("gemini"), dict):
        raise SystemExit("ERROR: config.gemini が必要です")
    gem: dict[str, Any] = cfg["gemini"]
    if not str(gem.get("model") or "").strip():
        raise SystemExit("ERROR: config.gemini.model が必要です")
    if not str(gem.get("api_key_file") or "").strip():
        raise SystemExit("ERROR: config.gemini.api_key_file が必要です")
    if not isinstance(cfg.get("taxonomy"), list) or not cfg["taxonomy"]:
        raise SystemExit("ERROR: config.taxonomy（配列）が必要です")

    try:
        sleep_between = float(gem["sleep_seconds_between_requests"])
        max_retries = int(gem["max_retries_per_file"])
        sleep_between_retries = float(gem["sleep_seconds_between_retries"])
    except KeyError as e:
        raise SystemExit(f"ERROR: config.gemini.{e.args[0]} が必要です") from e
    if sleep_between < 0 or sleep_between_retries < 0 or max_retries < 0:
        raise SystemExit("ERROR: sleep/max_retries は 0 以上で指定してください")

    out_dir = Path(str(cfg["output"]["dir"]))
    taxonomy = set(cfg["taxonomy"])
    return out_dir, gem, taxonomy, sleep_between, max_retries, sleep_between_retries


def run_one(
    *,
    md_path: Path,
    work_root: Path,
    out_dir: Path,
    model: str,
    api_key: str,
    rubric: str,
    schema: dict[str, Any],
    taxonomy: set[str],
) -> int:
    """Markdown 1ファイルを処理して、PROMPT/JSON を出力する。"""
    # 入力Markdownを読む
    body = read_text(md_path)

    # 出力JSONに入れる source（原稿ルートからの相対パス）を作る
    try:
        source = str(md_path.resolve().relative_to(work_root)).replace("\\", "/")
    except Exception:
        source = str(md_path)

    # プロンプトを構築して保存する（再現性・デバッグ用）
    prompt = build_prompt(rubric=rubric, schema=schema, source=source, body=body)
    prompt_path = (out_dir / f"{md_path.name}.PROMPT.md").resolve()
    write_text(prompt_path, prompt + "\n")

    # Gemini API で生成（生テキスト）を取得
    text = gemini_generate_text(model=model, prompt=prompt, api_key=api_key)

    # 生成テキストから JSON オブジェクト部分だけを抽出してパース
    try:
        report_obj = json.loads(extract_json_text(text))
    except Exception as e:
        raise SystemExit(f"ERROR: Geminiの出力をJSONとして解釈できませんでした（{e}）\n---\n{text[:2000]}\n---")

    # レポート形状の簡易検証（taxonomy/必須キー/型など）
    errs = validate_report_shape(report_obj, taxonomy)
    if errs:
        for e in errs:
            print(f"ERROR: {e}", file=sys.stderr)
        return 2

    # 正規化（トリム・並び替え）し、メタ情報を付与
    norm = normalize_report(report_obj)
    norm.setdefault("meta", {})
    norm["meta"]["generated_by"] = "gemini-api"
    norm["meta"]["model"] = model
    norm["meta"]["generated_at"] = _dt.datetime.now(tz=_dt.timezone.utc).isoformat()

    # JSON を保存し、出力パスを標準出力に出す（スクリプト側で拾いやすい）
    out_path = (out_dir / f"{md_path.name}.json").resolve()
    write_json(out_path, norm)
    print(str(out_path.relative_to(work_root)).replace("\\", "/"))
    return 0


def run_one_with_retries(
    *,
    md_path: Path,
    work_root: Path,
    out_dir: Path,
    model: str,
    api_key: str,
    rubric: str,
    schema: dict[str, Any],
    taxonomy: set[str],
    max_retries: int,
    sleep_between_retries: float,
) -> int:
    """単一ファイル処理をリトライ付きで実行する。"""
    last_rc = 0
    for attempt in range(0, max_retries + 1):
        try:
            last_rc = run_one(
                md_path=md_path,
                work_root=work_root,
                out_dir=out_dir,
                model=model,
                api_key=api_key,
                rubric=rubric,
                schema=schema,
                taxonomy=taxonomy,
            )
        except SystemExit as e:
            msg = e.code
            if msg:
                print(str(msg), file=sys.stderr)
            last_rc = 2
        if last_rc == 0:
            break
        if attempt < max_retries and sleep_between_retries > 0:
            time.sleep(sleep_between_retries)
    return last_rc


def load_config(work_root: Path, path: Path | None) -> dict[str, Any]:
    """設定ファイルを読み込む（原稿側 `.logiclint/` を優先し、無ければ同梱を使う）。"""
    if path is None:
        # 優先順:
        # 1) 原稿ルート（cwd）配下の ./.logiclint/logiclint.config.json
        # 2) ツール同梱（=リポジトリ/イメージ内）の ./.logiclint/logiclint.config.json
        candidate = work_root / ".logiclint" / "logiclint.config.json"
        if candidate.exists():
            path = candidate
        else:
            tool_cfg = Path(__file__).resolve().parents[2] / ".logiclint" / "logiclint.config.json"
            path = tool_cfg
    if not path.exists():
        raise SystemExit(f"ERROR: 設定ファイルが見つかりません: {path}")
    user_cfg = read_json(path)
    if not isinstance(user_cfg, dict):
        raise SystemExit(f"ERROR: 設定ファイルは JSON object である必要があります: {path}")
    return user_cfg


def main(argv: list[str] | None = None) -> int:
    """CLI エントリーポイント。引数解析→設定読込→対象を処理する。"""
    # 文字化け対策（主に Windows 環境）
    force_utf8_stdio()
    argv = list(sys.argv[1:] if argv is None else argv)

    # 引数パーサを構築
    p = argparse.ArgumentParser(
        prog="logiclint",
        description="原稿の内部論理不整合を、固定スキーマJSONで出力させるツール。",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    p.add_argument(
        "--config",
        default="",
        help="設定ファイル（省略時: ./.logiclint/logiclint.config.json を優先し、無ければツール同梱を使用）",
    )
    p.add_argument("--model", default="", help="Geminiモデル名（省略時: configの gemini.model）")
    p.add_argument("--recursive", action="store_true", help="ディレクトリ配下の .md を再帰的に順番に処理する")
    p.add_argument("target", nargs="?", help="対象Markdown（ファイル or ディレクトリ）")

    # 引数が無い/targetが無い場合はヘルプを出して終了
    if not argv:
        p.print_help(sys.stderr)
        return 0
    args = p.parse_args(argv)
    if not args.target:
        p.print_help(sys.stderr)
        return 0

    # 実行起点（カレントディレクトリ）を原稿ルートとして扱う
    work_root = Path(os.getcwd()).resolve()

    # 設定ファイルパス（--config 指定があれば優先。Windows表記も吸収）
    cfg_path: Path | None = None
    if args.config:
        # Windows の ".\foo.json" や "a\b\c.json" を Linux でも解釈できるように正規化する。
        cfg_user = normalize_user_path(args.config)
        cfg_path = (work_root / cfg_user).resolve() if not cfg_user.is_absolute() else cfg_user

    # 設定ファイルをロード（原稿側 `.logiclint/` を優先）
    cfg = load_config(work_root, cfg_path)

    # config を検証し、実行に必要な値を取り出す
    out_dir_rel, gem, taxonomy, sleep_between, max_retries, sleep_between_retries = validate_config(cfg)

    # CLIの --model があれば config より優先
    model = (args.model or str(gem["model"])).strip()

    # 出力ディレクトリは原稿ルート配下に解決する
    out_dir = work_root / out_dir_rel

    # APIキーを設定ファイル指定のパスから読む（原稿ルート基準）
    key_file = str(gem["api_key_file"])
    key_path = (work_root / key_file).resolve()
    api_key = get_api_key_from_file(key_path)
    if not api_key:
        raise SystemExit(f"ERROR: APIキーを読み取れませんでした: {key_file} ({key_path})")

    # 同梱の rubric/schema を読み込む
    rubric, schema = load_default_assets()

    # target のパスを正規化して実パスに解決する
    target = normalize_user_path(args.target)
    target_path = (work_root / target).resolve() if not target.is_absolute() else target

    # 出力先ディレクトリを作成
    out_dir.mkdir(parents=True, exist_ok=True)

    # 再帰実行（ディレクトリ配下の .md を順番に処理）
    if args.recursive:
        if not (target_path.exists() and target_path.is_dir()):
            raise SystemExit(
                f"ERROR: --recursive のときは引数にディレクトリを指定してください: {target} ({target_path})"
            )
        md_files = iter_md_files(target_path)
        for i, md in enumerate(md_files):
            # 1ファイルずつ実行（ファイル単位でリトライ）
            rc = run_one_with_retries(
                md_path=md,
                work_root=work_root,
                out_dir=out_dir,
                model=model,
                api_key=api_key,
                rubric=rubric,
                schema=schema,
                taxonomy=taxonomy,
                max_retries=max_retries,
                sleep_between_retries=sleep_between_retries,
            )
            if rc != 0:
                return rc
            # 連続実行時の待機（rate limit / クォータ対策）
            if sleep_between > 0 and i < (len(md_files) - 1):
                time.sleep(sleep_between)
        return 0

    # 単発実行（1ファイル）
    if not (target_path.exists() and target_path.is_file()):
        raise SystemExit(f"ERROR: ファイルが見つかりません: {target} ({target_path})")
    return int(
        run_one(
            md_path=target_path,
            work_root=work_root,
            out_dir=out_dir,
            model=model,
            api_key=api_key,
            rubric=rubric,
            schema=schema,
            taxonomy=taxonomy,
        )
    )

