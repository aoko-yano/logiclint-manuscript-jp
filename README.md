## logiclint（文章の内部論理Lint）

LLM（Gemini API）に「内部整合性の観点」を固定して当て、**JSON（固定スキーマ）**で指摘を返させ、原稿の編集に使うためのツールです。

### 特徴
- **rubric固定**: 観点は `logiclint/assets/rubric.md`
- **スキーマ固定**: 出力形は `logiclint/assets/schema.json`
- **最短コマンド**: `logiclint <path>`（ディレクトリは `--recursive`）
- **秘密はファイル固定**: `.logiclint/secret.json`（環境変数は使わない）

---

## 使い方（Docker推奨）

### 1) APIキー（1回だけ）
対象プロジェクト（原稿のルート）に、次のファイルを作成します（gitignore推奨）。

`.logiclint/secret.json`

```json
{ "gemini_api_key": "PASTE_YOUR_KEY_HERE" }
```

### 2) 単発実行（1ファイル）
PowerShell（Windows）:

```powershell
# 原稿ディレクトリに移動して、tool repo の logiclint.ps1 を呼ぶ
pwsh "<TOOL_REPO>/logiclint.ps1" "path/to/file.md"
```

### 3) 再帰実行（ディレクトリ）

```powershell
pwsh "<TOOL_REPO>/logiclint.ps1" --recursive "path/to/dir"
```

---

## 出力
既定で、原稿ルート直下の `logiclint-out/` に出ます。

- `logiclint-out/<入力ファイル名>.json`
- `logiclint-out/<入力ファイル名>.PROMPT.md`

---

## 設定
設定ファイルは `.logiclint/logiclint.config.json` です。

- 既定: ツール同梱の `.logiclint/logiclint.config.json` を使います
- 上書き: 原稿ルートに `.logiclint/logiclint.config.json` を置くか、`--config` で明示します

