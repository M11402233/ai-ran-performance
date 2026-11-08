# 本輪實驗驗收

狀態：**部分完成／未通過；不得宣稱整輪完成**。遠端流程狀態：`stopped`。

- [ ] 至少一組具有可重現性的 DU-only baseline
- [x] 有效的 DU 工作負載及量測紀錄
- [ ] 完成 shared / split CPU 資源配置比較
- [x] 有一張能解釋觀察結果與限制的圖

## 驗收依據

- 至少一組具有可重現性的 DU-only baseline：0 batches passed the unchanged ten-attempt baseline gate and recorded thread audit.
- 有效的 DU 工作負載及量測紀錄：19 evidence-verified runs; decoder activity, complete interval logs, per-second CPU affinity and RT policy audited.
- 完成 shared / split CPU 資源配置比較：Requires both matching baseline gates, all 40 matrix attempts, valid S0 controls, and >=3 repeat-matched valid pairs at each DQN thread level. Invalid fractions remain reported.
- 有一張能解釋觀察結果與限制的圖：overview.png plus caption.md; valid/invalid counts, baseline gate, paired observations, metric and VM limitations.

baseline 通過表示同一批十次可重複，不是跨日期／跨主機重現的證明。
比較的三組有效配對下限是交付完整性檢查，不是放寬 baseline CV 或 RT 門檻，也不是統計功效保證。

## 觀察

計畫 20 次；已嘗試 20 次；證據有效 19 次。
- S1 shared RT≤0：FAIL/pending；CV={'median_interval_avg_us': 2.013246703681568, 'median_interval_max_us': 21.807838504204483, 'max_interval_max_us': 31.095367282714825}；原因=['median_interval_max_us CV exceeds 5% or cannot be calculated', 'max_interval_max_us CV exceeds 5% or cannot be calculated', 'baseline RT failure messages exceed declared per-second ceiling']。
- S2 split RT≤0：FAIL/pending；CV={'median_interval_avg_us': None, 'median_interval_max_us': None, 'max_interval_max_us': None}；原因=['one or more invalid baseline runs', 'median_interval_avg_us CV exceeds 5% or cannot be calculated', 'median_interval_max_us CV exceeds 5% or cannot be calculated', 'max_interval_max_us CV exceeds 5% or cannot be calculated', 'baseline RT failure messages exceed declared per-second ceiling']。

## 圖與資料

[總覽圖](overview.png)／[圖說](caption.md)／[完整性與無效比例](quality-summary.csv)／[所有 run](all-runs.csv)。
有硬體計數時另附 cache-overview.png 與 perf-summary.csv；沒有就不產生假 cache 數據。

## 未完成時的下一步

- 未取得通過 baseline：先依保留原因檢查 RT 權限、host 排程、有效 decoder 與固定工作量；不要事後調整門檻或挑成功 run。
- shared/split 正式比較未完成：保留診斷圖；兩種 baseline 都過同一協定後，才補完整矩陣。
- guest vCPU 分核不能排除 host 實體核心／SMT／LLC 競爭。每秒 avg/max 不是 task median/P99；RT 訊息不是唯一 deadline miss。
- 此 DQN 是可控制的合成環境訓練負載，非生產用 RAN 控制器。
