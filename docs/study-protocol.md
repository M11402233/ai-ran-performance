# S0 → DQN → 分核：一般終端執行協定

本協定取代舊 CPU arithmetic 矩陣。新版入口是 `scripts/host_study.sh`，舊 `run_matrix.py` 與 `run_perf.sh` 僅保留供重現舊實驗。

## 1. 一般 VM 終端準備

以下指令必須在你自己 SSH 登入 VM 的一般終端執行。本 agent 工作階段的 NoNewPrivs=1、CapBnd=0，無法切換成一般主機權限；在此重跑不構成主機 baseline。

```bash
cd /home/cindy2/ai-ran-performance
python3 -m venv .venv-study
.venv-study/bin/python -m pip install -r requirements-study.txt
# 若缺 venv / perf，先由管理員安裝與 guest kernel 相符的套件，例如 Ubuntu：
# sudo apt-get install python3-venv linux-tools-common linux-tools-$(uname -r)
```

`host_study.sh` 用 sudo 啟動採集器與 gNB，gNB 自行設定 FIFO/RR threads，DQN 維持 SCHED_OTHER。每次啟動與採樣都驗證實際 policy；有提升優先權失敗訊息或沒有 RT worker，run 判無效。不要把整個 Python runner 用 chrt 設成 RT，否則 DQN 可能繼承錯誤優先權。

也可以用 `sudo setcap cap_sys_nice+ep ./bin/gnb` 授予 gNB 所需 capability，但 file capability 的 gNB 可能影響非 root 的 perf attach／proc 權限；提供的 sudo wrapper 可避免此採集權限落差。修改／重新解壓 binary 後需重新驗證 capability；ZIP 不保留 file capabilities。

## 2. 先跑十次 S0，失敗就停

預先指定最小關注效應，預設為延遲 20%，gate 為 CV ≤5%（效應的四分之一）。若目標為 10%，第一批量測前就加 `--effect-pct 10`，gate 將為 CV ≤2.5%；後續 baseline／matrix 必須使用同樣參數。這是工程接受門檻，不是功效分析，也不保證能偵測到指定效應。

```bash
bash scripts/host_study.sh baseline --layout shared
```

固定 5 MHz、1 test UE、time_scaling=1、3 main-pool threads，30 秒條件暖機＋60 秒採樣。共十次，每個失敗 attempt 都保留，不補跑成功樣本替換。所有十次都有效，且以下三個跨 run CV 都低於門檻，才通過：

- 每次「每秒 enqueue_avg」的中位數。
- 每次「每秒 enqueue_max」的中位數。
- 每次「每秒 enqueue_max」的最大值。

預設 baseline 每秒 `Real-time failure` 訊息上限為 0。若研究確實允許非零，需在第一批量測前明訂 `--max-rt-per-second N` 並沿用，不因結果難看才放寬。零 warning 仍不是零 deadline miss 的證明。

結果目錄會印在終端。看 `results/processed/該目錄/report.md`、`baseline-gate.json`、`quality.csv` 與圖。任何無效、遺漏或高變異都阻擋後續矩陣。若 gate 失敗，先檢查 RT policy、host 超額配置、vCPU pinning／steal、DU 工作負載與版本，調整後建立全新 baseline 批次，保留失敗批次。

為公平比較分核，再在沒有 DQN 的 DU 0–3 配置跑十次：

```bash
bash scripts/host_study.sh baseline --layout split
```

split baseline 也必須過 gate。這額外十次避免把「縮小 DU CPU 配額」與「DQN 競爭」混為一談。不要只挑十次中成功的部分計算 gate。

## 3. 兩種 baseline 都通過才跑矩陣

把目錄換成剛完成的兩批實際路徑：

```bash
bash scripts/host_study.sh matrix \
  --baseline-shared results/raw/baseline-shared-實際時間 \
  --baseline-split results/raw/baseline-split-實際時間
```

矩陣會重新讀原始 log 計算 gate，不單憑一份 PASS 檔。binary、配置、採樣時間、collector、host boot ID、門檻或程式改變，都需重新驗證 baseline。4 個 DQN 等級（0／1／2／4）× 2 種配置 × 5 次，固定 seed 隨機順序。加入 S0 作同時期控制；矩陣中 S0 失效或 RT 訊息超上限，立即停止增加條件，未嘗試的 runs 明列為未執行。

- shared：DU 與 DQN 都使用 guest CPU 0–7。
- split：DU 使用 0–3，DQN 使用 4–7。

gNB main-pool 與 RU 的 affinity 寫進每次配置，並以 taskset 設定啟動 mask；每秒驗證所有存活 threads 的實際 affinity，超出指定集合即無效。這是 guest vCPU 分離，不代表 host 端不同實體核心、獨立 LLC 或 NUMA 隔離；如有 SMT sibling，需另外記錄 host 映射。main-pool threads 在兩種配置都固定為 3。

DQN：同一個 CPU PyTorch trainer，16 維 observation、4 個 actions、256×256 MLP、replay buffer 20,000、batch 128、target network 每 100 updates 同步、epsilon 0.1。使用可重現的合成離散控制環境，有 environment interaction、replay、Bellman target 與 optimizer update；不是把一般整數運算改名，也不是生產用 RAN DQN 或特定公告模型的重現。1／2／4 表示 PyTorch intra-op 計算 threads，inter-op 固定 1；程序另有管理 threads，全部實際 thread masks 都保存。

DQN 與 DU 在條件下共同暖機。AI 吞吐量為每秒完成的 minibatch optimizer updates，與環境步數不同。每個完整 UTC 秒記錄 steps、elapsed、steps/s，最後不完整秒排除。

## 4. perf / vPMU

wrapper 會暫存原 perf_event_paranoid，設定為 1，結束或 Ctrl-C 後嘗試恢復，不寫 sysctl.conf。如果 sudo 授權過期，終端會印出手動恢復指令。請勿同時執行其他會修改該 sysctl 的實驗。

程式先實測 generic hardware cache-references、cache-misses、instructions、cycles；只有 perf --version 或 perf list 成功不算 vPMU 驗證。若事件未支援、未計數、有效 running coverage 低於 90% 或分母為零，run 不產生有效 cache 結論。generic cache 事件不能直接命名為 L1/L2/LLC miss。

如果 sudo 與 paranoid=1 後仍無硬體事件，管理員需在 KVM host／VM CPU 設定檢查 vPMU passthrough，可能需要停機變更 CPU/PMU 設定。guest 不能替 host 啟用它。保留 perf 錯誤輸出交管理員，不直接把錯誤歸因為單一 KVM 開關。

若 vPMU 無法提供，明確選 scheduling-only，兩批 baseline 都要用此模式重新跑：

```bash
bash scripts/host_study.sh baseline --layout shared --collector proc
bash scripts/host_study.sh baseline --layout split --collector proc
bash scripts/host_study.sh matrix --collector proc \
  --baseline-shared results/raw/baseline-shared-實際時間 \
  --baseline-split results/raw/baseline-split-實際時間
```

此模式不修改 paranoid、不報告 cache／IPC、不宣稱硬體瓶頸；仍要求 RT 權限與真實分核核對。wrapper 用 sudo 執行，因此不必再給 binary setcap。

## 5. 分析與交付

每批自動輸出到 `results/processed/批次名/`：

- `runs.csv`：所有 planned／attempted／valid runs、失敗原因、每 run 中位數／最大值、AI throughput。
- `decoder-intervals.csv`：每個保留區間的 avg/max、工作計數，附 valid flag。
- `per-second.csv`：每秒 FAPI RT failure／skipped-slot 訊息次數與 DQN updates/s，包含無效採樣 run。
- `quality.csv`：各條件 invalid/attempted 比例、planned、未執行數，不能只看 valid-only 圖。
- 圖：有效每秒延遲分布、每 run DU latency vs AI throughput、含無效樣本的每秒 RT 訊息、baseline stability 與完整性。

每秒 avg 的分布中位數不是 task latency median；每秒 max 的最大值不是 P99。FAPI RT 訊息可能同一 slot 有 DL／UL 多筆或被限流，因此不能說是唯一 missed-slot 次數。圖表不再使用「run 平均值的平均」。有效 interval pooled CDF 有 run 內相關性，不拿每秒樣本當獨立重複做顯著性宣稱。

量測成功後，一次打包 code＋所有彙整 CSV／PNG／report（不含逐筆 JSON、JSONL 或 raw log）：

```bash
python3 scripts/package_study.py
```

## 目前實際驗證狀態

2026-10-30：受限 agent 只有靜態／流程測試。主機前檢查已因 NoNewPrivs=1 停止，未執行十次 baseline，沒有新 DQN／cache 實測圖。PyTorch 未安裝，因此 DQN 訓練數值與性能尚未實跑驗證。shared／split 的 gNB 配置已用現有 binary --dryrun 通過。測試中的合成 log 只用於驗證 gate／統計／繪圖，不交付為實測結果。

## 官方依據

- Linux perf 權限：https://docs.kernel.org/admin-guide/perf-security.html
- CAP_SYS_NICE：https://www.man7.org/linux/man-pages/man7/capabilities.7.html
- PyTorch CPU threads：https://docs.pytorch.org/docs/stable/generated/torch.set_num_threads.html
- DQN 演算法參考：https://docs.pytorch.org/tutorials/intermediate/reinforcement_q_learning.html
- srsRAN affinity schema 以本機對應版本 `apps/services/worker_manager` 與 `apps/units/flexible_o_du/split_dynamic` 為準，並已 dry-run；不假定最新版文件與既有 binary 完全相符。
