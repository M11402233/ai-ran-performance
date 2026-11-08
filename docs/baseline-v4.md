# Baseline v4：DU 固定，只改 AI 位置

制定日期：2026-11-08，尚未開始任何 v4 量測。v1–v3 所有批次維持原判定 FAIL，不用 v4 規則重新判讀。

## 為什麼改（與結果好壞無關的理由）

1. **split 的 DU 沒有空閒核心。** v3 split 中 gNB 的 4 顆 CPU 上每顆都有一條 FIFO 執行緒（RU=0、workers=1–3），gNB 的其他輔助執行緒（log、metrics、控制）只能用 RT 剩下的時間。srsRAN 原本的 `spare_cpus = min(avail_cpus, 3)` 就是為這些執行緒保留空間，而 [worker 修正](worker-fix-20261102.md) 把它覆蓋掉了。v3 中 worker 數相同，split 的 enqueue_avg 卻是 shared 的 15–40 倍（1498–3923 µs 對 99–105 µs），這和上述機制吻合，但尚未證實是因果關係。
2. **RU 放在 CPU 0。** 中斷與 housekeeping 預設集中在 CPU 0，不適合放對時序最敏感的執行緒。
3. **兩組比較條件有混雜。** v3 shared 的 DU 可用 0–5，split 只能用 0–3，所以兩組的差異同時混了「DU 核心數」和「AI 位置」兩個因素。
4. **max-of-max CV 本身就不穩。** 「每秒最大延遲的最大值」是 60 個極端值裡再取最大值，跨 run 的變異本來就大，這是這個統計量的性質。
5. **啟動失敗發生在採樣之前。** DU 一直沒進入 active PHY 時，還沒有觀察到任何樣本，所以記錄下來再重新啟動並不是在挑結果。

## CPU 配置（`configs/cpu-layout-v4.csv`）

| 角色 | shared | split |
|---|---|---|
| housekeeping（OS／中斷）+ observer | 0 | 0 |
| RU timing thread | 1 | 1 |
| main pool（固定 3 workers） | 2–4 | 2–4 |
| gNB 空閒核心（不放 RT 執行緒） | 5 | 5 |
| gNB 程序整體允許範圍 | 1–5 | 1–5 |
| AI（兩組都是 2 顆） | 3–4（與 workers 重疊） | 6–7（獨立） |

`study_layout.validate_v4` 會強制檢查以下條件：兩組的 DU、RU、pool、spare、housekeeping 必須完全相同；AI 核心數相同；spare 必須等於 DU 扣掉 RU 和 pool；housekeeping 不在 DU 內；AI 不碰 RU、spare 或 housekeeping。新機器上若 logical CPU 0–7 不是 8 顆獨立實體核心，就要先改寫這份 CSV，並在量測前記錄下來。

## Gate v4

沿用 v3 的部分：UL-only、5 MHz、1 UE、30 秒暖機 + 60 秒採樣、10 次有效 run、CV ≤ 5%、主要 RT 上限 0／唯一的 RT ≤ 1 備援規則、不補採、不挑 run。

修改的部分：

- **CV gate 只檢查兩個指標**：每秒平均延遲的中位數、每秒最大延遲的中位數。max-of-max 仍然計算 CV 並報告，但不當作 gate。
- **啟動失敗可以替換，次數有上限**：DU 在 30 秒內沒有 active decoder，或在進入 active PHY 前就退出，標記為 `startup_failure` 並重新啟動，每組 baseline 最多替換 3 次。RT 權限失敗不算在內。進入 active PHY 之後的任何失敗（暖機、採樣、稽核）仍然判為無效，會擋住 gate。超過 3 次就判 FAIL，所有啟動紀錄都保留。
- `gate_version` 和 `startup_replacement_cap` 寫在 context 與 fingerprint 裡，matrix 必須使用相同的 context 才能解鎖。

## 新增的診斷證據

- 每秒的執行緒快照增加 `cpu_ticks`（utime+stime）：任一執行緒每秒增量接近 CLK_TCK，代表它在忙等。
- 每個 run 開始前和結束後都存 `/proc/interrupts`、`/proc/softirqs`，用來確認中斷是否落在 DU CPU 上。
- `scripts/diagnose_host.sh kernel|live`：前者掃 kernel log 並讀 RT throttle 計數器，後者在 baseline 執行時跑 pidstat 和 mpstat（per-thread CPU%、per-CPU %irq／%steal）。

## 舊 VM kernel log 掃描（2026-11-08，未重跑）

`journalctl -k --since 2026-10-30` 共找到兩個相關事件，沒有 RCU stall、soft lockup 或 hung_task：

| 時間（UTC） | 訊息 | 對應的 run |
|---|---|---|
| 10/30 23:02:01 | `clocksource: Long readout interval, skipping watchdog check: cs_nsec: 34895664809 wd_nsec: 34895662834` | 原版 shared run 02 採樣結束時刻 |
| 10/30 23:13:40 | `sched: RT throttling activated` | 原版 split baseline 開始後 6 秒 |

判讀與限制：

- 只要有 RT throttling，就代表某顆 CPU 上的 RT 執行緒吃滿了 95% 頻寬，這支持「RT 執行緒忙等或密度過高」的設計面解釋。但這條訊息每次開機只印一次，11/7 的 v2／v3 是否仍有 throttling，從 log 看不出來，要用新的 `cpu_ticks` 或 throttle 計數器確認。
- clocksource watchdog 有約 35 秒沒有執行，而且兩個時鐘一致，代表時間確實過去了，但 timer 被延遲。可能是 host 暫停了 VM，也可能是 timer／softirq 被 RT 執行緒餓住。單憑這一筆無法分辨。
- 這些都是當時原版 binary 和舊 layout 下的事件，不能直接代表 v3 的原因。

## 既有 v2／v3 每秒證據分析（2026-11-08，未重跑）

工具：`analysis/cpu_time_diag.py`，資料來源是 run 中每秒存下的 `/proc/stat` 和 observer schedstat。

| 觀察 | shared v3 | split v2／v3 |
|---|---|---|
| CPU 0–3 平均 idle | 0.9–2.5% | 0.3–1.7% |
| RT CPU 的 sys 比例 | CPU 0 95%；workers 約 21% | 46–96% |
| 有 gNB 輔助執行緒、但沒有 RT 的 CPU | 4–5（sys 13–19%） | 沒有 |
| 每秒 steal 最大值 | 3.9% | 2.4% |
| steal > 5% 的秒數 | 0 | 0 |

三次停頓（4.26／8.07／16.87 秒）的情況一致：

- CPU 0–3 都接近 99% busy。
- CPU 4–7 照常累積 tick（約 100 tick/秒），steal ≈ 0。
- observer 自己的 CPU 6–7 幾乎 100% idle。
- observer schedstat 顯示停頓期間只執行了 3–7.5 ms，等待 runqueue 的時間 ≤ 0.5 ms，只有 2–3 個 timeslice。

判讀：

- **不是 VM 被暫停。** guest 在停頓期間持續累積 tick 和 busy 時間，而且 steal 接近 0。
- **observer 不是在等 CPU，而是在 kernel 內被阻塞。** 它在等某個只能在 CPU 0–3 上完成的工作或鎖，例如 SCHED_OTHER 的 gNB 執行緒或 per-CPU kworker，而這些 CPU 被 RT 執行緒佔滿了。
- **split 的 gNB 輔助執行緒沒有地方跑。** 包括 2 條 SCHED_OTHER 的 gnb 執行緒，以及 FIFO 的 io_broker_epoll。shared 有 CPU 4–5 可以跑這些輔助工作，所以沒有出現停頓。
- 這些證據支持 v4 的「保留空閒核心、housekeeping 不放 RT」，但真正卡住的是哪一把鎖或哪一個 kworker，還要等 v4 跑過或用 kernel stack 確認。
- 10/30 那次 35 秒的 watchdog 空檔仍然無法解釋。目前 steal 很低，但 host 有超額配置，新的 run 仍要持續監看 steal。

## 舊 VM 上的 v4 split 診斷（2026-11-08，batch `baseline-split-20261108T131931731621Z`）

完成 3 個 attempt，第 4 個在 Ctrl-C 時被中斷；這批只用來診斷，不算 baseline。

| 指標 | v3 split | v4 00 | v4 01 | v4 02 |
|---|---:|---:|---:|---:|
| 每秒 enqueue_avg 中位數 | 1498–3923 µs | 85 µs | 86 µs | 86 µs |
| 每秒 enqueue_max 中位數 | — | 455 µs | 537 µs | 607 µs |
| max-of-max | — | 1626 µs | 10712 µs | 10181 µs |
| RT 訊息（總數／每秒峰值） | 122–160 行/秒（峰值） | 8／5 | 757／108 | 751／58 |
| observer 最大延遲 | 4–17 秒停頓 | 0.109 秒 | 0.001 秒 | 無停頓 |

- worker CPU 2–4 約 58% busy、41% idle；RU 與每個 worker 約 50% CPU，不是 100% 忙等；空閒的 CPU 5 只用了約 4%。
- 01 的 RT 訊息集中在 t+16～t+41 秒，這段期間 CPU 都沒滿（≤60%），每秒 steal 0–2%。單看 1 秒解析度的 /proc/stat，還不能排除 host 超額配置造成的次秒級搶占（1% steal 就等於每秒 10 ms，足以讓 1 ms slot 遲到）。
- 結論：DU 飢餓和 observer 停頓在 v4 都已消失；剩下的是間歇性的 RT burst，這是 VM／host 層的嫌疑，要等 host 專用核心或裸機再驗證。

## 執行順序

1. 在舊 VM 上（選做、低成本）：`sudo bash scripts/diagnose_host.sh kernel`；另外詢問管理員 host 是否有定期備份或快照、vCPU 是否綁定實體核心、是否超額配置。
2. 在舊 VM 上各跑 1–2 次 v4 split：在 root 終端執行 `.venv-study/bin/python scripts/run_study.py baseline --layout split --collector proc --config configs/du-uplink-only.yml --layout-plan configs/cpu-layout-v4.csv`，同時在另一個終端執行 `sudo bash scripts/diagnose_host.sh live 120`，兩次 attempt 後按 Ctrl-C 停止。這批會留下中斷紀錄，只用來診斷，不算 baseline。
3. 在新的裸機上：先適配 CSV，凍結程式與配置，再執行 `sudo bash scripts/start_baseline_v4.sh`。
