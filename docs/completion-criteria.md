# 本輪完成標準與明天要看的成果

目前已啟動的量測保留原 binary、配置、程式 fingerprint、CV 與 RT gate。新增內容只在後處理／打包時分析。正在執行中的 remote orchestrator 結束時會呼叫更新後的 package_study.py，因此這輪不必為了新增報告重啟。

## 四項驗收（自動勾選）

| 項目 | 可勾選的證據 |
|---|---|
| 至少一組可重複的 DU-only baseline | 至少一批十次 S0 全有效，三項延遲摘要 CV ≤5%，符合該批預定 RT 上限；另重查每秒實際 thread masks 與 FIFO/RR 記錄。十次同批重複不代表跨日或跨機重現。 |
| 有效 DU 工作負載及量測紀錄 | 至少一次完整有效採樣；decoder 每個保留區間均有工作、報告無缺漏、每秒 RT／affinity 證據完整。有效不代表零即時警告。 |
| 完成 shared／split 比較 | 同一配置／協定的兩批 baseline 都通過，40 個矩陣條件都已嘗試，S0 controls 有效且 RT 不超標；每種 DQN 0／1／2／4 threads 至少 3 組相同 repeat 的有效 shared/split 配對。所有無效比例都要報告。 |
| 一張能解釋結果與限制的圖 | overview.png 實際生成且有實測紀錄；caption.md 說明 baseline gate、有效／無效／未執行、延遲與吞吐量、觀察成立的範圍與 VM 限制。 |

三組配對是新增的交付完整性要求，不改變原先每條件計畫五次的設計，不修改 baseline gate，不等於統計功效或顯著性證明。若只有兩種 S0 的資料，只能畫 baseline CPU 配置的探索結果，不勾選 DQN shared/split 正式矩陣完成。

## 輸出

自動收尾時產出到 `deliverables/`：

- `completion.md`：先看這份，四個勾選項目、依據、未完成原因與下一步。
- `overview.png`：六格總覽（baseline 可重複性、每秒 RT、DU／DQN 取捨、配對延遲變化、有效／無效／未執行、限制）。
- `caption.md`：中文圖說。
- `shared-split-comparison.csv`：只配對相同矩陣、相同 DQN threads 與 repeat，不跨原批／備援批拼資料。
- `quality-summary.csv`：按條件的 invalid/attempted 比例、未執行數。
- 有有效硬體 perf 數據才產出 `cache-overview.png`、`perf-summary.csv`。
- `du-dqn-study.zip`：code、配置、上述成果及各批彙整資料；不含逐筆 JSON／JSONL／raw log。

同時保留每批 `results/processed/remote-session-時間/` 的版本，不用較新的結果覆蓋先前失敗證據。若渲染失敗，第四項不勾選，報告列出錯誤，不把舊圖當新圖。來源 raw log 留在 VM 供稽核。

## 本輪不通過時的獨立低負載補測

另提供 `configs/du-uplink-only.yml`：5 MHz、1 UE、time_scaling=1、啟用 PUSCH、停用 PDSCH。保留真正 decoder 工作，不藉空載取得零延遲。與原本雙向 UE 負載的差異是實驗場景，不是同一工作量下的性能最佳化，兩者不得混合計算。

本輪結束後，才可在一般 SSH 終端啟動獨立 UL-only 場景：

```bash
cd /home/cindy2/ai-ran-performance
sudo bash scripts/start_remote_study.sh \
  --session-name ai-ran-study-ul \
  --config configs/du-uplink-only.yml
```

新場景仍跑十次 shared S0、十次 split S0，沿用 CV≤5% 與原本 RT 0→1 的預先備援條件；通過才進相同場景的 DQN 矩陣。新配置必須先於該批量測選定，不拿舊 baseline 解鎖新配置。啟動器會檢查既有量測鎖，拒絕同時啟動第二批。

目前只驗證這份配置能由對應 gNB binary dry-run 接受，尚未證明它能達到穩定 gate；降低 DL 負載也未必解決 VM host 排程問題。不保證明天四項都能勾選，保證每項都有數據或明確的未完成原因。

## 明天查看／下載

```bash
cat deliverables/completion.md
# 若想手動重建最終分析與 ZIP：
.venv-study/bin/python scripts/package_study.py
```

一般量測以 root 寫入結果時，手動重建需改成 `sudo .venv-study/bin/python scripts/package_study.py`。在本地電腦下載：

```bash
scp cindy2@主機IP:/home/cindy2/ai-ran-performance/deliverables/du-dqn-study.zip .
```
