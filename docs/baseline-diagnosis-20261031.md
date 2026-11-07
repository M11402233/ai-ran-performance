# Baseline 排查（2026-10-31）

原始量測與驗收結果保留不變。以下為既有資料診斷，不是新實驗。

## shared
- attempts=10, valid=10
- RT warning lines（全部 attempts）=3734
- 有效 run 的 median_interval_avg_us 範圍=75.0–78.0
- 每秒 main_pool worker 數分布={3: 600}
- main_pool (policy, priority) 分布={(1, 96): 1800}
- guest aggregate steal %：median=0.0000, max=0.4161（不能排除 host 排程延遲）

## split
- attempts=10, valid=9
- RT warning lines（全部 attempts）=293558
- 有效 run 的 median_interval_avg_us 範圍=292.0–344.0
- 每秒 main_pool worker 數分布={1: 600}
- main_pool (policy, priority) 分布={(1, 96): 600}
- guest aggregate steal %：median=0.0000, max=0.1339（不能排除 host 排程延遲）

## 判讀與後續
- 設定 nof_threads=3，但需以上述實際 worker 數為準；配置 metadata 不能證明實際 thread 數。需核對 binary 的有效配置、worker 建立與 thread 命名，尚未確認根因。
- FIFO policy=1 且有 RT priority 的紀錄，表示並非單純完全未取得 RT 權限。
- split 沒有 DQN 時已劣化；目前不能歸因於 DQN，也不能由順序執行資料證明分核因果。
- 原始 log 出現 late DL/UL request 與 discarded uplink slot。缺 decoder 區間的 run 保留無效。
- 下一輪先核對有效 main_pool 數，再以獨立 UL-only 場景完整重跑兩批 baseline；不混入舊資料、不放寬 CV/RT gate。
- agent sandbox 無 capabilities、NoNewPrivs，無法執行需 root 的實機 RT 重測；需一般 SSH 終端啟動。

```bash
cd /home/cindy2/ai-ran-performance
sudo bash scripts/start_remote_study.sh --session-name ai-ran-study-ul --config configs/du-uplink-only.yml
```

## 原始碼定位
本機來源 apps/services/worker_manager/worker_manager.cpp 的 get_default_nof_workers（約 326–357 行）：
`spare_cpus=min(avail_cpus,3)`；回傳 `max(min(nof_workers,avail_cpus-spare_cpus),1)`。
即使明訂 nof_threads=3，shared mask=8 得到 3；split mask=4 得到 1，與全部 1200 個 snapshots 一致。
這是本機來源邏輯與 binary 觀察的吻合，未宣稱已從乾淨來源重建驗證。

兩配置同時改變 worker 數，構成比較的混雜因素。現有有效 run 僅表示可用量測紀錄，不代表符合「固定三 workers」設計。
已在 run_study.py 的 RT thread audit 加入實際三 workers 檢查，未符合時直接停止。
UL-only 改工作負載不會解除 worker cap；在修正 binary 或另訂兩組都採一 worker 的獨立協定之前，不應啟動上面的重跑指令。
若採一 worker，需同步修改協定、fingerprint 與檢查，兩組重跑，不能沿用現有 baseline。
