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

### 実測結果 (2026-09-20, ling-3.0-flash-fin:free @ Novita)

| 項目 | Strands | LangGraph | CrewAI |
|---|---|---|---|
| 実装LOC | 78行 | 115行 | 110行 |
| LLM呼び出し数 | 3-5回 (自律ループ) | 1回 (base) / 2回 (tight) | 4回固定 (2エージェント直列) |
| トークン合計 | 2,370 (base) | 2,007 (base) | 2,532 (base) |
| LLMレイテンシ合計 | 4.2s | 4.7s | 3.8s |
| reasoning文字数 | 277 | 6,163 | 363 |
| venvサイズ (依存の重さ) | 262MB / 81 pkg | 71MB / 45 pkg | 699MB / 142 pkg |

### マトリクス実験 (27ラン: 3フレームワーク×3シナリオ×3ラン)

シナリオ: base=80-120語 / tight=95-105語(検証ループ強制発火) / drift=word_count
スキーマの引数リネーム(text→content、モデルは新スキーマに追従する必要)

| 最終語数 (3ラン) | base | tight | drift |
|---|---|---|---|
| Strands | 99,100,85 (ぶれ15) | 103,104,93 (ぶれ11) | 94,93,105 (ぶれ12) |
| LangGraph | 96,92,83 (**ぶれ13**) | 103,101,100 (**ぶれ3**) | 99,83,91 (ぶれ16) |
| CrewAI | 96,96,96 (**ぶれ0**) | 99,99,101 (ぶれ2) | 96,96,96 (ぶれ0) |

**記事の核となる発見 (全て traces/ の生データから)**:

1. **「明示的制御が決定論を買う」の定量化**: LangGraphはbaseで語数ぶれ13
   (1発書き切り、検証なし)だが、tightでグラフループが発火してぶれ3に減少
   (77%減)。コストはトークン2.5倍(2,007→5,262)・レイテンシ2.5倍(4.7→11.8s)。
2. **CrewAIの「決定論的に見える動き」**: temperature=0+roleプロンプト支配で
   base/driftとも最終出力が3ラン完全同一(96/96/96)。ただしLLM呼び出し構造は
   常に4回固定=柔軟性はない。
3. **Strandsの自律ループ**: tightで3ラン全てループ発火、しかし呼び出し数は
   [5,3,4]と可変(モデルが完了を判断)。ぶれ11に減らしつつ柔軟性を保持。
   最初のパスで検証をスキップするランがある非決定性もそのまま観測データ。
4. **スキーマドリフト耐性**: シンプルな引数リネームなら全フレームワークのモデルが
   新スキーマに100%追従(誤引数0)。エラー復帰は不要だった。

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

- 全フレームワークのLLM通信が `traces/llm_calls_<framework>[__<run_label>].jsonl`
  に記録される: リクエスト(システムプロンプト、ツールスキーマ、メッセージ履歴)、
  レスポンス(SSE含む生データ)、トークン数、レイテンシ、ステータス。
- ランラベルは `X-Run-Label` ヘッダで付与(クライアントがヘッダを送らない場合は
  run labelの接頭辞 `<fw>__` から推測)。`runs/run_matrix.py` が27ランを一括実行し、
  `runs/analyze_matrix.py` がスキーマ認識付きで集計(→ `artifacts/matrix_report.json`)。
- Strands/LangChainはSSEストリーミングで応答するため `proxy/parse_sse.py` で
  まとめ直す(パース済みは reasoning / tool_calls / usage を統一形式で持つ)。
- APIキーはトレースに入らない(プロキシで除去)。

## 注意事項

- Strands/LangChainはSSEストリームを要求する。`_raw` に全SSEが入る。
- CrewAI は X-Framework ヘッダを送らない (unknown になる)。
- poolside/laguna-s-2.1:free は頻繁に429。nemotron-3-ultra-550b は34秒程度かかる。
- モデル選定は `inclusionai/ling-3.0-flash-fin:free` (フルループ1.8sで最速、安定)。
