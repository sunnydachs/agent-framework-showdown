# Agent Framework Showdown — Strands vs LangGraph vs CrewAI

同一タスク「tech news digest エージェント」を3フレームワークで実装し、
LLM通信をローカル記録プロキシに通して動きを正確に比較するプロジェクト(記事素材)。

## セットアップ

```bash
# venv (Python 3.12 — crewai is <3.14 required)
uv venv .venv-strands --python 3.12 && uv pip install --python .venv-strands/bin/python "strands-agents[litellm]"
uv venv .venv-langgraph --python 3.12 && uv pip install --python .venv-langgraph/bin/python langgraph langchain-openai
uv venv .venv-crewai --python 3.12 && uv pip install --python .venv-crewai/bin/python crewai
```

`.env` に `OPENROUTER_API_KEY` (OpenRouterキー)を置く。プロキシが読み込む。

## 実行

```bash
# 1. 記録プロキシ起動 (ターミナル1)
python3 proxy/rec_proxy.py --port 8118

# 2. 各フレームワーク実行 (ターミナル2、実行前に traces/ をクリア)
rm -f traces/*.jsonl
OPENAI_BASE_URL=http://127.0.0.1:8118/v1 ./.venv-strands/bin/python frameworks/strands_digest.py
OPENAI_BASE_URL=http://127.0.0.1:8118/v1 OPENAI_API_KEY=dummy-key ./.venv-langgraph/bin/python frameworks/langgraph_digest.py
OPENAI_BASE_URL=http://127.0.0.1:8118/v1 OPENAI_API_KEY=dummy-key CREWAI_TELEMETRY=false OTEL_SDK_DISABLED=true ./.venv-crewai/bin/python frameworks/crewai_digest.py

# 3. トレースをリネーム (フレームワークラベル)
#    (X-Frameworkヘッダ未対応のクライアントは unknown になるので手動リネーム)

# 4. レポート生成
python3 proxy/parse_sse.py
python3 proxy/report.py
```

## 実測結果 (2026-09-20, ling-3.0-flash-fin:free @ Novita)

| 項目 | Strands | LangGraph | CrewAI |
|---|---|---|---|
| 実装LOC | 78行 | 115行 | 110行 |
| LLM呼び出し数 | 4回 (自律ループ) | 1回 (纯テキスト変換) | 4回 (2エージェント直列) |
| トークン合計 | 3,506 | 1,966 | 2,533 |
| LLMレイテンシ合計 | 4.7s | 5.0s | 3.9s |
| reasoning文字数 | 277 | 6,163 | 363 |
| venvサイズ (依存の重さ) | 262MB / 81 pkg | 71MB / 45 pkg | 699MB / 142 pkg |

### 動きの違い (トレースから確認済み)

- **Strands**: モデル駆動。メッセージ履歴が2→4→6→8と成長。モデルが自分で
  get_headlines呼び→下書き→word_count呼び(77語と判定)→自ら修正→最終回答。
  検証と修正がプロンプト指示のみで成立。LLMが停止を判断。
- **LangGraph**: グラフ駆動。LLM呼び出しは下書き執筆の1回のみ。
  ツール呼び出しは全て開発者がワイヤした決定論的ノード(collect/verify)。
  分岐・ループ・リトライはコードの構造として保証。reasoning 6,163文字
  (モデルは毎回大量に考えているが、フレームワークは状態だけ見ている)。
- **CrewAI**: ロール駆動。Researcher(2呼び出し: fetch+回答)→Writer(2呼び出し:
  下書き+検証)の直列ハンドオフ。各エージェントに独立したsystem prompt
  (role+goal+backstory)が注入される。

### 可観測性

- 全フレームワークのLLM通信が `traces/llm_calls_<framework>.jsonl` に記録される:
  リクエスト(システムプロンプト、ツールスキーマ、メッセージ履歴)、レスポンス
  (SSE含む生データ)、トークン数、レイテンシ、ステータス。
- Strands/LangChainはSSEストリーミングで応答するため `proxy/parse_sse.py` で
  まとめ直す(パース済みは reasoning / tool_calls / usage を統一形式で持つ)。
- APIキーはトレースに入らない(プロキシで除去)。

## 注意事項

- Strands/LangChainはSSEストリームを要求する。`_raw` に全SSEが入る。
- CrewAI は X-Framework ヘッダを送らない (unknown になる)。
- poolside/laguna-s-2.1:free は頻繁に429。nemotron-3-ultra-550b は34秒程度かかる。
- モデル選定は `inclusionai/ling-3.0-flash-fin:free` (フルループ1.8sで最速、安定)。
