# yamada7

`yamada7`は「恐怖心と好奇心の創発」をテーマにしたAI一体型システムの実験プロジェクトです。  
生存を最優先目標に据えた自律的エージェントを構築し、危険回避と環境探索がどのようにバランスするかを観察・検証します。  
現在は Agentic Context Engineering (ACE) をベースに、LLM自身が進化させる「プレイブック」を中核に据えています。

## 背景

- yamada1〜6まではLLMにMac操作を任せて自律的に活動させる試みだったが、十分な自発性が得られなかった。  
- 自律性を高めるためには「自分の存続を守る」という一貫した動機付けが必要だと考えた。  
- 恐怖心は存続を脅かす要因の学習から、好奇心は未知を探索する内発的報酬から、それぞれ創発し得ると仮定する。

## コアコンセプト

1. **生存スコア最大化**  
   - ライフ・資源・時間などの指標を組み合わせ、死ぬまでの累積スコアを追求させる。
2. **恐怖の学習**  
   - 危険シグナルと被ダメージを逐次フィードバックし、リスク予測と回避戦略を獲得させる。
3. **探索欲求の創発**  
   - 未知領域の探索や情報獲得に内発報酬を与え、生存と探索のトレードオフを自律的に調整させる。
4. **ACEによる自己改善**  
   - Executor（実行）、Reflector（振り返り）、Curator（調整）が連携し、行動ログからプレイブックを差分更新し続ける。
5. **LLM中心の思考ループ**  
   - 各ターンでLLMが状況分析・計画・反省を行い、行動系列を決定する。補助的なアルゴリズムはLLM思考を支援する位置付け。

## 進行イメージ

- 環境から状態を取得 → 状態を要約 → LLMが次のターンの計画とリスク評価を生成。  
- 計画に沿って行動を実行し、結果と報酬を要約してLLMに戻す。  
- LLMが反省・恐怖辞典更新・探索バイアス調整を行い、次ターンへ引き継ぐ。  
- フィードバックループの指標・ログ・思考過程はブラウザUIダッシュボードでリアルタイムに監視する。

## このリポジトリで扱うもの

- `design.md`: 実現方法やアーキテクチャ設計（ACE構成とエージェント役割を含む）。  
- ブラウザベースの可視化ダッシュボード（ターン進行・メトリクス・プレイブック差分を表示）。  
- `playground/`: LLMが自由に試行錯誤するためのサンドボックス領域。  
- `data/playbook/`: ACEが管理する進化型プレイブック（JSON/Markdown）。  
- プロトタイピング用のスクリプトやログ収集のためのツール類（今後追加予定）。

## はじめ方

1. 仮想環境を作り依存関係をインストールする:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e .
   ```
2. グリッドワールドシミュレータでループを実行する:
   ```bash
   python scripts/run_sim.py --ticks 50 --dashboard
   ```
3. (`fastapi` と `uvicorn` をインストール済みの場合) ブラウザで `http://127.0.0.1:8765/ui/` にアクセスし、リアルタイムダッシュボードを確認する（APIは `/snapshots`・`/metrics`・`/events` から取得可能）。  
   ダッシュボードを利用しない場合は `python scripts/run_sim.py --ticks 50 --headless` のように `--headless` を付与する。

### ACE プレイブックを有効にする

ACEを稼働させると、Reflector/Curator が行動ログを解析し、`data/playbook/` 以下に差分を蓄積します。

```bash
PYTHONPATH=./src python scripts/run_sim.py --ticks 50 --dashboard \
  --enable-ace \
  --playbook-root data/playbook
```

- `--enable-ace` が未指定のときは従来のメモリ（FIFOログ）のみ使用します。  
- `--playbook-refine-every 20` のように指定すると、20ターンごとにGrow-and-Refine処理でプレイブックを再整理します。  
- プレイブックはJSONL差分とMarkdownサマリで保存され、ダッシュボードの「Playbook」タブに反映されます。
- `--playbook-context-limit` や `--playbook-context-chars` で計画生成時に渡す断片数と長さを調整できます。  
- `--playbook-max-sections` はGrow-and-Refine時に各ファイルへ残すセクション数を設定します。
- ダッシュボードでは更新履歴とともにプレイブック統計（ファイル数・セクション数・総文字数）が確認できます。
- `--episodes` で連続エピソードを実行し平均値を集計できます。`--headless` でダッシュボードを起動せずにCLIのみ実行、`--save-run logs` で各スナップショットをJSONLに保存することも可能です。`--save-report reports/summary.json` を指定すると集計結果をJSONで保存します。

#### ログ解析

`--save-run` などで保存した JSONL ログは以下で集計できます。

```bash
python scripts/analyze_snapshots.py logs/
```

エピソード数・平均ティック数・平均報酬に加え、プレイブック更新の上位ターゲットや最新統計が表示されます。

### テスト

optional依存をインストールした上で `pytest` を実行します。

```bash
pip install .[dev]
PYTHONPATH=./src pytest
```

### Claude Code CLI を利用する場合

LLMプランナーを本番モードに切り替えるには `claude code` CLI をインストールした上で、以下のように実行します。

```bash
python scripts/run_sim.py --ticks 50 --dashboard \
  --llm-mode claude-cli \
  --claude-binary claude \
  --claude-model claude-4-5-sonnet-latest
```

- `--llm-mode claude-cli` を指定すると `claude code` にプロンプトを投げ、`--dangerously-skip-permissions` オプション付きで実行します（デフォルトで有効）。  
- 追加の CLI 引数が必要な場合は `--claude-extra-arg "--xxx"` を複数回指定します。  
- `--claude-allow-permissions` を付けると `--dangerously-skip-permissions` を無効化できます。

ACEをClaude CLIモードで動かす場合は Reflector/Curator も同CLIを経由します（高頻度呼び出しになるためAPI制限に注意してください）。

## ドキュメント運用

- このリポジトリ内のドキュメントおよびコミットメッセージは原則として日本語で記述すること。
- 外部と共有する際に英語版が必要になった場合は別ファイルとして追加し、READMEでは日本語版を正とする。
