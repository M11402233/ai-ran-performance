> 歷史紀錄：新版 S0 十次 gate、DQN 與完整分核流程見 [study-protocol.md](study-protocol.md)。下列舊結果不是新版實測。

# perf cache 量測

預設 collector 已由 proc 改為 perf。執行 `bash scripts/run_perf.sh` 會使用 5 MHz 配置，4 種條件各 5 次，30 秒暖機、60 秒採樣。先驗證 baseline：

```bash
bash scripts/run_perf.sh --conditions S0 --repeats 1
```

量測主機需要可執行的 `perf`、可用的硬體 PMU、python3、pandas、matplotlib、taskset，以及 `bin/gnb` 的動態庫。請由主機管理員提供符合 kernel 的 linux-tools 與 PMU 存取權。腳本不變更系統權限。

每次先確認 active PHY、完成暖機，再啟動背景負載與 perf。perf stat 以 `-p DU_PID` 量測 DU 所有既有 threads，預設繼承後續 threads；背景 Python workers 不列入 DU 計數器。CPU_BG_PIN 沿用 vCPU 6,7，需要至少這兩個可用 vCPU。

事件：cache-references、cache-misses、instructions、cycles。採樣期間的程序硬體計數器與既有 executor 量測並行；cache 計數器涵蓋整個 DU，並非僅 decoder executor。perf 啟動時間與 proc 採樣有少量偏差，不應逐筆時間對齊。

輸出：`deliverables/cache-results.png`、`cache-summary.csv`。每個點是一個成功 run，不是 P99。miss rate = misses / references × 100；MPKI = misses / instructions × 1000；IPC = instructions / cycles。generic cache 事件的硬體含義依 CPU/PMU 而異，不能直接稱為 L1/L2/LLC miss，也不能僅憑這些值推論 cache 因果瓶頸。

缺 perf、權限不足、不支援事件、未被排程、任一事件 running coverage <90%，或分母為零時直接失敗；不以零取代。高覆蓋率仍可能包含 perf multiplex scaling，事件並未強制同一 PMU group。既有 run 品質檢查仍可用 `analysis/summarize.py RUN_DIR`，應搭配其 active decoder 與即時警告表評估正式比較。

原始 log / JSON 僅保留本機供稽核，不逐一交付。原始紀錄若要重畫圖需保留；ZIP 僅含程式、配置、文件、既有 gNB binary 與彙整結果。

## 本次執行狀態（2026-10-30）

當前工作環境找不到 perf；`/proc/sys/kernel/perf_event_paranoid` 為 4。量測前檢查已實際執行並停止，尚未取得任何 perf cache 數據，因此沒有 cache 實測結果圖。交付中的 `previous-latency-results.png` 是先前 10 MHz pilot 的延遲圖，僅供回顧，並非 cache 圖。

已通過 Python 語法檢查、perf CSV parser 的有效值/不支援/未計數/低覆蓋率檢查，以及暫存合成資料的繪圖流程測試。合成資料沒有納入交付，沒有用於實測結論。
