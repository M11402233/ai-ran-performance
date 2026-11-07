# UL-only v2：排查與下一輪協定

## 已確認的證據

上一輪 remote-session-20261107T145206Z：shared 9/10、split 7/10 證據有效，兩組 gate 都未通過，沒有 DQN 矩陣。

- split repeat=3 的 60 筆 snapshot 缺 2 個 wall-clock seconds，重複同一秒 3 次；repeat=8 缺 10 秒、重複同一秒 11 次。舊迴圈醒來後補採造成，並非 thread affinity 自動變更的證據。
- 兩次相鄰 snapshot 的 wall 間隔約 3.247／11.341 秒，CPU ticks 推估經過約 3.156／11.014 秒。較支持實際停頓，不能單憑此排除時鐘校正或確認 host scheduling 根因。
- 每組首筆 decoder 全部 interval 都是 nof_executes=0、nof_defers=0，並有 DL task queue full。不是僅因 readiness regex 漏認已有工作。首筆究竟為何失活仍未確定；保留失敗，不額外暖身後丟掉首筆或重試至成功。
- 三 workers 已在有效採樣出現，RT policy 亦生效；split enqueue 延遲仍高，不能把它單獨歸因於未取得 RT 權限。

## 腳本修正

1. 使用 monotonic deadlines 排程逐秒採樣，保留 wall-clock 秒以對齊既有 gNB logs。開始與完成採樣都必須落在該秒內；漏秒立刻失敗，不補採、不放寬完整性。
2. 新 run 的 run.json 記錄 thread_audit_required、main_pool_threads=3；read_run / baseline gate / 收尾共用逐秒 thread audit，檢查缺秒、重複、CPU mask、三 workers RT policy。舊批原始證據不修改。
3. readiness 接受最新 decoder report 的 executed 或 deferred 大於零，不再只看曾經有 deferred；啟動上限仍為 30 秒。
4. before/after 及逐秒 diagnostics 記錄 wall/monotonic 時鐘、/proc/stat（含每 CPU）、CPU/IO/memory PSI、observer schedstat/io、RT runtime/period。這些是診斷資料，不是 host 實體核心隔離證明。

## 下一輪：獨立 UL-only 場景

沿用 configs/du-uplink-only.yml：5 MHz、1 UE、PUSCH 開啟、PDSCH 關閉、time_scaling=1。這是降低 DL 負載的新場景，不是同工作量優化；不能與舊雙向資料合併。

- shared / split 均明訂且稽核 3 workers。
- shared DU CPU 0–7；split DU CPU 0–3，DQN CPU 4–7。
- 30 秒暖機、60 秒採樣、每配置 10 次。
- CV≤5%、RT≤0；沿用原來僅在兩組都只因 RT 失敗才可完整重跑 RT≤1 的規則。
- 兩組通過同一新 fingerprint 才啟動 40 次 DQN 矩陣。不承諾這個新場景必能過 gate。

## 啟動

```bash
cd /home/cindy2/ai-ran-performance
sudo bash scripts/start_next_study.sh
```

固定 session 名稱 ai-ran-study-ul-v2；既有 launcher 會拒絕重複 session 或同時運行的實驗。

進度查詢：`python3 scripts/study_status.py`。

agent 已嘗試 sudo -n 啟動，但 NoNewPrivs=1 阻擋升權，因此尚未開始新一輪；需在一般 SSH 終端執行上面一條啟動指令。
