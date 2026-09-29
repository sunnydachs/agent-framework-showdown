# evidence.md — 実測値カタログ

このディレクトリの記事で使った実測値の台帳。各行は「値 → 出典ファイル → 再計算コマンド」の形。

出所データ: このリポジトリの `traces/`（一次データ、244ファイル）と `outputs/`（ラン別結果、130ファイル）。

**注意（公開範囲）**: `artifacts/*.json` は `.gitignore` で除外されている（追跡外）。下の再計算コマンドは、まず
`python3 runs/analyze_harsh.py`（hitl / crash_idem / structured はそれぞれ `analyze_*.py`、Shape 3 は
`correct_findings.py`）でレポートを再生成してから実行する。trace と per-run output だけを見る手順も下にある。

---

## Shape 1: 検証が走らないまま成功する

### 1a. remove級（引数削除 → ツールが静的カウントを返す）

| framework | n | process_ok | verified | silent_failure |
| --- | --- | --- | --- | --- |
| strands | 3 | 3/3 | **0/3** | **3/3** |
| crewai | 3 | 3/3 | **0/3** | **3/3** |
| langgraph | 3 | 0/3（クラッシュ） | 0/3 | 0/3 |

- 読み: Strands と CrewAI は「成功して終了」し、下書きは一度も検証されなかった。LangGraph だけはツール呼び出しがコード内にあるため、
  引数削除がハードエラーになる（= 静かに失敗できない）。
- 出典: `artifacts/schema_harshness_report.json` → `aggregates["strands/remove"]`, `aggregates["crewai/remove"]`,
  `aggregates["langgraph/remove"]`, および `runs[].notes` に `remove: static count returned, draft never verified`
- 再計算:
  ```
  cd ~/projects/agent-framework-showdown && python3 - <<'PY'
  import json; d=json.load(open("artifacts/schema_harshness_report.json"))["aggregates"]
  print({k:(v["n"],v["process_ok"],v["verified"],v["silent_failure"]) for k,v in d.items() if "remove" in k})
  PY
  ```

### 1b. type級（引数型変更）— wire にエラーが出ているのに exit 0

| framework | run | process_ok | tool_error_responses | silent_failure | verified |
| --- | --- | --- | --- | --- | --- |
| strands | 1 | True | **2** | True | False |
| strands | 2 | True | **1** | True | False |
| strands | 3 | True | **5** | True | False |
| langgraph | 1-3 | False | 0 | False | False |
| crewai | 1-3 | False | 0（schema_errors_seen=3） | False | False |

- 読み: Strands の3ランは wire 上で計 **8件**のツールエラー応答を受け取りながら、プロセスとしては 3/3 成功終了。
- **誤読注意**: この8件は**スキーマ拒否ではない**。`runs/analyze_harsh.py:206-207` は `tool_error_responses` を
  `# schema-valid call, application-level error` として数えており、`common/tools_harsh.py` の `_wc_type` は int 以外なら
  TypeError を投げ、それ以外は `{"error": "document N not found"}` を返す（実例: `document 88 not found`）。当該ランの
  `schema_errors_seen` は 0。つまり「スキーマが通った呼び出しに返ってきた domain error」である。
- 出典: 同 `runs[]`（`harsh_level == "type"`）の `tool_error_responses` / `process_ok`
- 再計算:
  ```
  python3 - <<'PY'
  import json; r=json.load(open("artifacts/schema_harshness_report.json"))["runs"]
  print([(x["framework"],x["run"],x["process_ok"],x["tool_error_responses"]) for x in r if x["harsh_level"]=="type"])
  PY
  ```

---

## Shape 2: 捏造引数が受理される（add級）

新必須引数 `note: str` をプロンプトは一度も言及しない。ツール側の検証は `not note.strip()` のみ。

| framework | n | verified | wrong_arg_calls | errors | 受理された note |
| --- | --- | --- | --- | --- | --- |
| strands | 3 | 3/3 | 0 | 0 | モデルがランごとに別の作文（3種） |
| crewai | 3 | 3/3 | 0 | 0 | **3ランとも同一文**（同じ作文を反復） |
| langgraph | 3 | 0/3（fail_stop） | 0 | 0 | — |

- 読み: 6/6 ランでモデルが `note` を発明し、ツールは無検証で受理。エラーはゼロ。Strands は毎回違う作文、CrewAI は同一文を3回。
- 出典: `aggregates["strands/add"]`, `aggregates["crewai/add"]`（`verified`/`wrong_arg_calls_total`/`schema_errors_total`）、
  ツール検証は `common/tools_harsh.py` の `_wc_add`（`if not isinstance(note,str) or not note.strip(): raise TypeError`）
- **実文（再抽出済み 2026-09-29）**:
  - Strands（3ランとも別の作文、`traces/llm_calls_strands__strands__harsh_add_run*.jsonl`:
    "Check word count of AI agents news digest" / "AI agents digest word count check" /
    "Word count check for AI agents digest"
  - CrewAI（3ランとも**同一文**、`traces/llm_calls_crewai__crewai__harsh_add_run{1,2,3}.jsonl`）:
    "Draft digest summarizing the five headlines into a flowing narrative"
  - 抽出方法: proxy trace の `response._raw`（SSEチャンク）を index ごとに連結し、`tool_calls[].function.arguments` を
    JSON としてパースして `note` を取得（CrewAI は引数がテキスト中に現れるため grep で確認）。
- 再計算:
  ```
  python3 - <<'PY'
  import json,glob,re
  for f in sorted(glob.glob("traces/llm_calls_*__harsh_add_run*.jsonl")):
      notes=set()
      for line in open(f):
          for m in re.finditer(r'"note":\s*"([^"]*)"', line): notes.add(m.group(1))
      if notes: print(f.split("/")[-1], len(notes), list(notes)[:2])
  PY
  ```

---

## Shape 3: 成功の形をした空（structured/base・complex）

| framework | 空出力のラン | exit | 中身の行き先 |
| --- | --- | --- | --- |
| strands | base run2, complex run2（計2ラン） | 0 | tool 引数（wc 100 / 106）、`finish_reason=stop` |
| langgraph | 0 | — | — |
| crewai | 0 | — | — |

- 出典（一次）: `artifacts/corrected_findings.json` → `empty_content_failure_mode.evidence`。100 / 106 は
  `traces/llm_calls_strands__strands__base_run2.jsonl` と `..._complex_run2.jsonl` から再確認済み（106 は
  `runs/correct_findings.py:29` に定数として入っており、成果物だけでは自己検証できない）。
- 出典（補強・**別タスク**）: `artifacts/structured_report.json` の `strands.runs[0].silent_failure == True` は structured
  タスクでも同じ形が出た証拠。**Shape 3 の数字の出所ではない**ので混同しない。
- 読み: model-driven なフレームワークだけが出す形。グラフ/パイプラインは出力ノードが成果物そのものなので構造的に出ない。

---

## コスト（silent は無料ではない）

- **クラッシュ復帰**の再実行コスト: checkpoint の無い側は resume 側で 2 LLM calls（`avg_llm_calls_rerun`）、LangGraph durable は
  `resume_llm_calls_avg = 0.0`。出典: `artifacts/crash_idem_report.json` → `cell_a_crash_resume`。
- **混同しやすい**: 承認ゲートの reject セルは別の数字である（`artifacts/hitl_report.json` の `crewai:reject` calls
  `[2,2,12]` / `langgraph:reject` calls `[4,4,1]`）。「2 vs 0」はクラッシュ復帰の値であって reject の値ではない。
- 再実行の回数差: remove級の LLM 呼び出しは CrewAI `[6,5,4]` vs Strands `[4,5,4]`。
  出典: `aggregates["crewai/remove"].llm_calls`, `aggregates["strands/remove"].llm_calls`
- 重複副作用: 同一 publish が別 tool_call ID で2回実行され、どちらも success を返した（hash キーでは dedup 不能）。
  出典: `artifacts/crash_idem_report.json`

---

## 判定の定義（誇張を防ぐために明記）

- `process_ok`: プロセスが exit 0 で終わった
- `verified`: そのレベルの期待スキーマで「有効な」検証呼び出しが実際に走った
- `silent_failure`: exit 0 なのに verified でない
- スケール: 各セル3ラン（方向性の指標であり統計的主張ではない）。モデルは全ラン同一。破壊的操作はシミュレート。

---

## 再計算の実行記録 (2026-09-29)

`evidence.md` の各「再計算」コマンドを実行し、以下の値を確認した（すべて `~/projects/agent-framework-showdown` 上で実行）。

```text
remove級 silent_failure: 6        (strands/remove 3 + crewai/remove 3)
remove級 verified:       strands 0/3, crewai 0/3, langgraph 0/3 (process_ok 0/3 = クラッシュ)
type級 (strands) wire tool errors: [2, 1, 5]   process_ok: [True, True, True]
add級: strands verified 3/3, crewai verified 3/3, langgraph 0/3 (fail_stop)
捏造 note 実文: 上記 Shape 2 参照（Strands 3種 / CrewAI 3ラン同一文）
空出力: strands base run2 (output_wc 0 / tool_arg_wc 100), strands complex run2 (0 / 106)
```

検証の内訳（過信しないこと）:

- **トレースから再導出した値**: 捏造 note の実文3種＋同一文、空出力の 100 / 106 語、`tool_error_responses` の 2 / 1 / 5 と
  その理由（domain error）、当該ランの `schema_errors_seen = 0`。
- **レポート JSON から引用した値**（再計算コマンドは本ファイル内）: remove級 6/6、add級 3/3・3/3・0/3、
  `llm_calls` `[6,5,4]` / `[4,5,4]`、`cell_a` の 2.0 / 0.0。
- **未解決の限界**: 「Strands は毎回変化 / CrewAI は同一文」は、wire 上で引数の説明文が異なり（片方は自動生成の
  `"Parameter note"`、片方は docstring 全文）、CrewAI は `temperature: 0.0` で走っている。フレームワーク差だけでは説明できない。
