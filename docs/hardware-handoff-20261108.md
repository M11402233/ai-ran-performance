# 硬體重測前的實驗摘要（2026-11-08）

> 新機請改用 [baseline v4](baseline-v4.md)：v3 split 的 DU 沒有空閒核心，RU 放在 CPU 0，而且兩組的 DU 資源不同。v1–v3 的 FAIL 判定不變。

## 現階段結論

已有可運作的 DU 合成工作負載、CPU PMU 採集、逐秒 worker/RT/affinity 稽核與報告流程。現有 VM 所測配置尚無 baseline PASS；沒有正式 DQN 共置矩陣或 CUDA 實驗結果。這不證明必須有 GPU，也不證明硬體永遠無法通過。

明天優先驗證可控實體 Linux 主機上的 DU-only baseline。GPU 是後續 AI offload 比較軸，不是修復 DU baseline 的保證。

## 已完成的四輪主要紀錄

| 階段 | 主要結果 |
|---|---|
| 10/30，原版 baseline | shared 10/10、split 9/10 量測有效；之後發現實際 workers=3/1，存在混雜因素；gate FAIL |
| 11/7，worker 修正版 UL+DL | workers 同為 3；有效 9/10、7/10；RT、啟動失活與漏秒仍有問題；gate FAIL |
| 11/7，UL-only v2 | 有效 9/10、8/10；split 兩筆 monotonic 停頓 4.257/16.874 秒；gate FAIL |
| 11/7，UL-only v3 | RU=CPU0、observer=6–7；有效 10/10、9/10；gate FAIL |

## 最新 v3 最終結果

Session：remote-session-20261107T222535Z。流程已停止、sysctl 已恢復；無 DQN 矩陣。

| 指標 | shared | split |
|---|---:|---:|
| 有效／嘗試 | 10/10 | 9/10 |
| 每 run 的每秒 enqueue_avg 中位數範圍 | 99–105 µs | 1498–3923 µs |
| 各有效 run 的 RT 訊息峰值 | 30–62 行/秒 | 122–160 行/秒 |
| CPU generic cache miss rate | 21.04–22.68% | 20.17–21.61% |
| IPC | 0.885–0.915 | 0.950–1.007 |

shared 三項跨 run CV：平均延遲摘要 2.01%（符合 5%）、最大延遲摘要中位數 21.81%、最大延遲摘要最大值 31.10%。RT 超標，因此 FAIL。split 有一次約 8.074 秒 monotonic lateness，判無效；其 baseline CV 不計算。

19 個有效 run 都有 PMU 彙整。PMU 可讀不代表 baseline 通過，也不能單憑 cache miss rate 推論因果。完整 raw evidence 留在舊主機，本 source package 不包含。

## 腳本目前具備

- 明訂三個 workers 的 gNB patch；新主機必須重新 build，不能用舊 native binary。
- UL-only 場景與 v3 CSV role plan；兩組保留相同 worker 數。
- monotonic 排程、wall 秒完整性、漏秒立即失敗，不補採。
- runtime gate 與收尾共用逐秒 evidence audit，驗證 RU/pool/AI/observer CPU masks 與 policy。
- 十次完整 baseline、CV≤5%、主要 RT 上限 0；唯一預定 RT≤1 備援條件保持不變。
- 35 項回歸測試已通過；兩配置非 RT 程序 worker/mask smoke 通過。不是正式性能驗收。

## 新硬體首日執行順序

1. 讀根目錄 START_HERE.md、README.md、GPU_HANDOFF_PLAN.md；保留此包 provenance。
2. 記錄 CPU physical/logical topology、SMT、NUMA、RAM、kernel、GPU/driver、governor、RT throttling、PMU 權限。
3. 安裝依賴，以附帶 source 乾淨建置；source snapshot 已套 worker patch，不重複套用。
4. 適配 configs/cpu-layout-v4.csv；不能假設新硬體 CPU 0–7 表示八個獨立實體核心。不足時先改研究方案，重新記錄固定 worker 數與門檻。
5. gNB dry-run、35 項回歸測試、具權限的實際三 worker/RT/mask 檢查、PMU probe。
6. 凍結配置與程式，再跑新機兩種 layout 各十次 baseline。不要用 VM baseline 解鎖新機矩陣。
7. 通過後才做 CPU AI；CUDA runner 尚未實作，需依交接計畫完成後另凍結版本重驗 baseline。FlexRIC 監控為獨立階段。

每秒 avg/max 不是逐任務 P99；RT 訊息行數不是唯一 deadline miss；dummy RU 不是實際 UE/Core/RF throughput 實驗。
