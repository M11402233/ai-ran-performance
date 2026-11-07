> 歷史紀錄：新版 S0 十次 gate、DQN 與完整分核流程見 [study-protocol.md](study-protocol.md)。下列舊結果不是新版實測。

# 實驗協定與計畫差異

## 實際執行

- 單 cell，10 MHz，band 78，SCS 30 kHz，1T1R，1 test UE。
- dummy RU，time_scaling=1；CU-UP ngu.no_core=true，test mode 自動關閉 CU-CP Core 需求。
- 低頻寬使用本機版本官方 `cell_cfg_pucch_5_mhz_bw.yml` 降低 PUCCH 資源。
- executor report period 1000 ms，log metrics 開啟。未改 RAN 程式碼。
- 短版 pilot：5 秒暖機＋15 秒採樣，每條件 5 次，固定 seed 20261030 對全部 runs 隨機排序，依序執行。
- S0：DU only。S1：2 個 Python 整數運算 workers，50% duty。S2：8 workers，100% duty。
- CPU_BG_PIN：與 S2 相同 8 workers，背景工作限至 guest CPU 6、7；DU 配置不變。
- 自製 CPU 負載不是 stress-ng，也不是 AI，不冒充計畫 S3–S7。
- CPU_BG_PIN 不是 DU/AI 完整分核隔離：DU 可能仍使用 6、7，且背景工作的可用算力縮減；僅探索背景負載限核。
- 各 run 留存 config、stdout、gnb log、proc snapshots、thread masks、workload output 及 run.json。
- 採樣剔除 sample_start 後第一秒，避免第一個 interval 橫跨背景工作啟動時點；暖機與關機資料不納入。
- 主分析預先選定 `pusch_dec_exec`，CSV 同時保留所有 executors。
- 每個 run 取 interval enqueue_avg 的未加權平均與 interval enqueue_max 的最大值；不是所有 task 的加權平均，也不是 P99。
- nof_defers 是 API 工作派送計數，不能視為 deadline miss。無逐 task tracing，不宣稱 P95/P99。

## 正式版本

`python3 scripts/run_matrix.py --label formal-cpu` 預設 30 秒暖機＋60 秒採樣、每組 5 次。四組總計約 30 分鐘加啟停時間。pilot 完成不代表正式矩陣完成。

正式結果前須固定乾淨 source commit、確認 binary 來源、先穩定 baseline、排除 host 超額配置及其他工作、比較 profiling 開關的開銷。另需補 PyTorch CPU workload、AI progress、完整隔離對照及 PMU 診斷，才能回答完整 RQ1–RQ3。

CPU mask 記錄能驗證 guest affinity，不能證明 host 實體 core/cache 隔離。VM 的 steal time 由 `/proc/stat` 原始 snapshots 留存，可作後續混淆檢查；即使 steal=0 也不能證明獨占 host。

本批 pilot 為檢查啟動穩定性，未預先等待 active decoder；後續腳本已加入最長 30 秒 readiness gate。這是測試後的品質修正，不宣稱原批符合修正後協定。分析只保留採樣每個 interval 都有 decoder 工作的 runs，原資料不刪除。

補測 reduced-baseline：band 3、5 MHz、SCS 15 kHz、1 UE、1T1R；新增 readiness gate，30 秒暖機＋60 秒採樣，僅 1 次 S0。此設定與 10 MHz pilot 分開儲存，不能合併統計。
