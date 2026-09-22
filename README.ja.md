# agent-framework-showdown

**同一のダイジェストエージェントをStrands・LangGraph・CrewAIの3フレームワークで実装し、全LLM呼び出しを記録して動きを正確に比較するプロジェクト。**

[English](README.md) | 日本語

同一タスク・同一モデル・同一ツールで3フレームワークを27ラン実行し、全LLM通信をローカル記録プロキシに通しました。「どのフレームワークがどう違うか」を、感覚ではなくトレースファイルで答えます。

## タスク

テックニュースダイジェストエージェント:

1. `fetch_headlines`ツールで見出しを5本収集
2. 100語前後のダイジェストを執筆
3. `word_count`ツールで語数を検証(範囲外なら修正)

3フレームワークとも同じモデル・同じ記録プロキシ経由なので、ログが直接比較できます。

## セットアップ

```bash
# フレームワーク別venv (Python 3.12 — CrewAIは<3.14必須)
uv venv .venv-strands --python 3.12 && uv pip install --python .venv-strands/bin/python "strands-agents[litellm]"
uv venv .venv-langgraph --python 3.12 && uv pip install --python .venv-langgraph/bin/python langgraph langchain-openai
uv venv .venv-crewai --python 3.12 && uv pip install --python .venv-crewai/bin/python crewai
```

`.env` にLLM認証情報を置きます(OpenAI互換のエンドポイントなら何でも):

```bash
LLM_API_KEY=sk-...
LLM_BASE_URL=https://your-openai-compatible-endpoint.example.com
```

## 実行

```bash
# 1. 記録プロキシ起動 (ターミナル1)
python3 proxy/rec_proxy.py --port 8118

# 2. 各フレームワーク実行 (ターミナル2、実行前に traces/ をクリア)
rm -f traces/*.jsonl
OPENAI_BASE_URL=http://127.0.0.1:8118/v1 ./.venv-strands/bin/python frameworks/strands_digest.py
OPENAI_BASE_URL=http://127.0.0.1:8118/v1 OPENAI_API_KEY=dummy-key ./.venv-langgraph/bin/python frameworks/langgraph_digest.py
OPENAI_BASE_URL=http://127.0.0.1:8118/v1 OPENAI_API_KEY=dummy-key CREWAI_TELEMETRY=false OTEL_SDK_DISABLED=true ./.venv-crewai/bin/python frameworks/crewai_digest.py

# 3. 集計
python3 proxy/parse_sse.py
python3 proxy/report.py
```

再現性マトリクス(27ラン: 3フレームワーク×3シナリオ×3ラン):

```bash
python3 runs/run_matrix.py
python3 runs/analyze_matrix.py   # -> artifacts/matrix_report.json
```

追加実験(45ラン、すべて同一プロキシ経由):

```bash
# A: フレームワーク税 - 各フレームワークが最初のLLM呼び出しに追加するもの
python3 runs/analyze_tax.py

# B: タスク形状スケーリング - complex(分岐+2 fetch) vs base、9ラン
python3 runs/run_complex.py && python3 runs/analyze_scaling.py

# D: HITL - interrupt() vs human_input vs プロンプトのみ、18ラン
python3 runs/run_hitl.py && python3 runs/analyze_hitl.py

# E: 監査証跡の再構成 - トレースから監査人が何を復元できるか
python3 runs/analyze_audit.py

# F: 構造化出力の準拠 - strict JSON、9ラン
python3 runs/run_structured.py && python3 runs/analyze_structured.py

# G: クラッシュ復旧 + 冪等性 + リトライ後監査、34ラン
#    承認待ち中のSIGKILL vs checkpointerなし、位置キー vs コンテンツハッシュ
#    冪等キー vs なし、監査人が重複効果を検出できるか
python3 runs/run_crash_idem.py && python3 runs/analyze_crash_idem.py
```

## 実測結果 (2026年9月、単一モデル、27ラン)

| 項目 | Strands | LangGraph | CrewAI |
|---|---|---|---|
| 実装LOC | 78行 | 115行 | 110行 |
| LLM呼び出し数 | 3-5回 (自律) | 1回 (base) / 2回 (tight) | 4回固定 |
| トークン合計 (base) | 2,370 | 2,007 | 2,532 |
| LLMレイテンシ合計 | 4.2s | 4.7s | 3.8s |
| venvサイズ (パッケージ数) | 262MB (81) | 71MB (45) | 699MB (142) |

### 出力の安定性 (3ランの語数ぶれ、最大-最小)

| シナリオ | Strands | LangGraph | CrewAI |
|---|---|---|---|
| base (80-120語) | 15 | **13** | **0** |
| tight (95-105語) | 11 | **3** | 2 |
| drift (スキーマリネーム) | 12 | 16 | 0 |

### トレースが示したこと

- **LangGraph**はbaseモードでLLM呼び出し1回・一発書き切り、語数ぶれは13語。tightにすると明示的な検証/修正ループが発火してぶれは3に減少(−77%)。コストはトークン2.5倍(2,007→5,262)・レイテンシ2.5倍(4.7→11.8s)。**明示的制御は決定論を買えるが、トークンとレイテンシで払う。**
- **CrewAI**はbaseもdriftも3ラン完全に同一出力(96/96/96語)。temperature=0と役割プロンプトが支配的。引き換えに、LLM呼び出しは4回固定で柔軟性はない。
- **Strands**は自分のループ内で自己修正しました。モデルが77語の下書きを「下限未満」と判定し、自分で104語に修正。呼び出し数はランごとに可変([5, 3, 4])。model-drivenな制御は適応性を直接買い、停止判断をモデルに任せるのも設計の一部です。

### スキーマドリフト耐性

`word_count`ツールの引数名をリネーム(`text`→`content`)しました。3フレームワークすべてのモデルが**新**スキーマに追従し、誤引数は0。エラー復帰は一度も発火しませんでした。(LangGraphはツール呼び出しがコード内なので、そもそも影響を受けません)

## 実験4 (G): クラッシュ復旧・冪等性・リトライ後監査

さらに34ラン、同じプロキシ・同じモデル。3つの問い: プロセス死亡後も状態は生き残るか、LLMがリトライしたとき冪等キーは重複副作用を防げるか、監査人はトレースだけから何が起きたかを証明できるか。全データ: `artifacts/crash_idem_report.json`(`runs/run_crash_idem.py && runs/analyze_crash_idem.py`で再生成)。

### クラッシュ復旧(承認待ち中にSIGKILL、新プロセスが再開)

| フレームワーク | 永続化 | 再開 | 状態生存 | 再開のLLM呼び出し |
| --- | --- | --- | --- | --- |
| LangGraph | durable checkpointer | **0.01-0.02秒** | 3/3 | **0**(状態復元のみ・再推論なし) |
| LangGraph | checkpointerなし | 0.0秒 | 0/3 | -(状態はプロセスと共に死亡) |
| Strands | なし | 平均4.9秒 | ゼロから再実行 | 平均5.3回 |
| CrewAI | なし | 平均4.2秒 | ゼロから再実行 | 平均2.0回 |

durable checkpointerは**再開**と**やり直し**の分かれ目。LangGraphの0.01秒はcheckpointerがグラフを復元する時間で、LLM呼び出しは一切不要。なしでは同じ「再開」に見えても実際はフル再実行でトークンコストを全額払い直す。

issue-8764の形状(最初のdurable checkpoint前にクラッシュ): テストしたLangGraphバージョンでは空スレッドの再開は**エラーを上げずに成功した**(`EmptyInputError`は未発生)。失敗記録ギャップの挙動はバージョン依存なので、エラーの有無に頼らず外部のacceptance ledgerを持つこと。

### 冪等性(リトライ時の重複実行、3ラン平均)

| キー戦略 | 同一引数リトライ | 言い換えリトライ |
| --- | --- | --- |
| 位置キー(`workflow:step:tool`) | 重複1、全てdedup | 重複3、**33% dedup**(2.67はcaller-bug拒否) |
| コンテンツハッシュ(引数のsha256) | 重複1、全てdedup | **重複1、0% dedup — ハッシュが変わりdedupをすり抜けた** |
| キーなし | 重複1.33、0% dedup | 重複1、0% dedup |

核心: **コンテンツハッシュキーは、モデルがリトライで引数を言い換えた瞬間に静かに失效する** — そしてLLMのリトライはreplayではなく再推論なので、必ず言い換える。位置キーは引数のバイト列でなく意図(workflow内の位置)を識別するので言い換えに耐える。重複呼び出しはすべてワイヤー上で**異なるtool_call ID**を持っており、プロトコル層では何も検出できない。

### リトライ後監査(トレースだけの監査人、8番目の事実=重複検出)

プロキシは全試行を記録するので、根拠・重複の可視性・dedupの証明可能性・リトライ証拠の復元率は全6セルで100%。トレースだけ読む監査人は、重複を見て、どの試行がdedupされたかを見て、その理由(ledgerの結果がtool応答に入る)まで追える — ただしそれは記録がワイヤーレベルだから。フレームワークレベルのトレース表面では二重発火は一切見えない。

## 可観測性の設計

ローカル記録プロキシが全フレームワークの前に立ります:

- `proxy/rec_proxy.py` — :8118で待ち受け、OpenAI互換の任意エンドポイント(`LLM_API_KEY` + `LLM_BASE_URL`)へ中継し、全呼び出しを `traces/llm_calls_<framework>[__<run_label>].jsonl` に記録。リクエスト全文(メッセージ、ツールスキーマ、システムプロンプト)、レスポンス生データ(SSE/JSON)、トークン数、レイテンシ、HTTPステータス。APIキーは書き込み前に除去。
- `X-Run-Label` ヘッダでトレースをラン別に分割。カスタムヘッダを送らないクライアントは `<fw>__` ラベル接頭辞からフレームワークを推測。
- Strands/LangChainはSSEストリーミングで応答するため、`proxy/parse_sse.py` がストリームを非ストリーム応答と同じ形式(content / reasoning / tool_calls / usage)に再構築。
- `runs/run_matrix.py` が27ランを約270秒で一括実行し、`runs/analyze_matrix.py` がスキーマ認識付きの誤引数検出で `artifacts/matrix_report.json` に集計。

フレームワーク横断で同じ形式というのが、この比較を正直にする核です。全員の前に1本のプロキシを置くだけで、直接比較可能なログが手に入ります。

## 正直な限界

- 3ラン/セルはトレンド確認であり、統計的な主張ではない。標準的な目安ではmedian推定の下限は約30ラン。
- タスクが1種類(ツール1個+検証1個)は、model-drivenフレームワークが最も輝く領域。LangGraphのグラフ構造が本領を発揮する複雑な分岐・承認・並列ワークフローは未検証。
- 結果はモデル依存。別のモデルではreasoningの量、ツール呼び出し傾向、出力ぶれが変わります。
- 依存フットプリントとバージョンは変化が速く、ここの数字は初回インストール時点のもの。

## リポジトリ構成

```
frameworks/   フレームワーク別実装 (Strands / LangGraph / CrewAI)
common/       共通の決定論的ツール2個
proxy/        記録プロキシ + SSE再構築 + 初回レポート
runs/         マトリクス実行 (base 27ラン + complex 9ラン) と集計
traces/       記録されたLLM通信 (ランごとに1ファイル) - 一次データ
outputs/      各フレームワークが書き出すラン別結果JSON
artifacts/    git管理外: 解析成果物。runs/*.py で再生成できる
              (analyze_tax, analyze_scaling, correct_findings, analyze_matrix)
```

## ライセンス

MIT
