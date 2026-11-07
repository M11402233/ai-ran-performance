# AI–RAN：先穩定 baseline，再量 DQN／DU 取捨

2026-11-02 更新：已修正 split 的 main-pool worker 截斷問題，兩種 CPU mask 實際均建立 3 workers；bin/gnb 已切換修正版。驗證範圍與重測指令見 [修正紀錄](docs/worker-fix-20261102.md)。舊結果仍為 2/4，尚無修正版 RT/CV 驗收結果。

遠端自動流程：[docs/remote-study.md](docs/remote-study.md)，在一般終端執行 `sudo bash scripts/start_remote_study.sh`。需先具備 tmux／perf／python3-venv；腳本會在 tmux 內準備 Python 依賴並依預先固定規則執行。

四項完成標準與明日成果：[docs/completion-criteria.md](docs/completion-criteria.md)。收尾自動產出 `deliverables/completion.md`、`overview.png` 與單一 ZIP；不通過的項目保留原因。

新版協定：[docs/study-protocol.md](docs/study-protocol.md)。舊 `run_matrix.py`／`run_perf.sh` 與 CPU arithmetic 圖僅供歷史重現；正式流程改用 `host_study.sh`，不再以舊均值圖回答研究問題。

在一般 VM 終端執行，先準備環境：

```bash
cd /home/cindy2/ai-ran-performance
python3 -m venv .venv-study
.venv-study/bin/python -m pip install -r requirements-study.txt
bash scripts/host_study.sh baseline --layout shared
# shared 十次通過後，分核 S0 也需十次
bash scripts/host_study.sh baseline --layout split
# 兩批都通過，代入實際輸出目錄
bash scripts/host_study.sh matrix \
  --baseline-shared results/raw/baseline-shared-實際時間 \
  --baseline-split results/raw/baseline-split-實際時間
python3 scripts/package_study.py
```

預設最小關注效應 20%，baseline 十次各延遲摘要的 CV ≤5%，無無效 run，且每秒 RT 失敗訊息為零。未達標即阻擋 DQN。這是暫定工程 gate；若目標效應不同，第一批執行前設定 `--effect-pct`，後續保持一致。

DQN 壓力是 1／2／4 PyTorch intra-op threads，記錄每秒 minibatch optimizer updates。shared 為雙方用 0–7；split 為 DU 0–3、DQN 4–7。兩種配置固定 3 個 gNB main-pool threads，每秒驗證所有 threads 的 mask 與 RT policy。

wrapper 使用 sudo 讓 gNB 設 RT，暫時將 perf_event_paranoid 改為 1 並嘗試恢復。若硬體 PMU／vPMU 不可用，明確以 `--collector proc` 重跑兩批 baseline 與矩陣，報告只作排程層級觀測。詳見協定。

每批產出 interval 分布、DU latency vs AI throughput、每秒 RT 訊息、invalid/attempted 比例與未執行數。單一交付 ZIP 為 `deliverables/du-dqn-study.zip`，含 code 與彙整 CSV／圖／報告，不逐一附 raw JSON。

## 執行狀態

本 agent 環境 NoNewPrivs=1、無 capabilities，且缺 perf 與 PyTorch。新版程式與合成 log 流程測試已通過，兩種 affinity 配置已由 gNB dry-run 驗證；尚未在一般終端跑十次 baseline，也未完成 DQN 訓練實跑。沒有新 cache 或 DQN 實測結果圖。不要把歷史 CPU-only 圖視為新版結果。

歷史測試見 [docs/report.md](docs/report.md)、[docs/hardware-inventory.md](docs/hardware-inventory.md)。本次仍無真實 UE/Core/RF throughput、逐任務 P99 或 host 實體核心隔離證據。

## 版本與來源

既有本機建置的 gNB 複製到 `bin/gnb`，版本 25.10.0、commit d2f4b70；原始 source 存在未提交 E2 修改，patch 保留於 `docs/existing-source.patch`。未宣稱從乾淨來源重建或已安裝計畫指定 OCUDU。AGPL license 見 `docs/srsran-LICENSE`；此研究目錄沿用原本機 binary。

## 開發檢查

```bash
python3 -m unittest discover -s tests -v
```
