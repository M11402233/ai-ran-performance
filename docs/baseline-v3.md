# Baseline v3：RU 與採集器 CPU 分離

更新（2026-11-08）：正式 v3 已結束，shared 10/10、split 9/10 有效，但兩組 gate 均未通過；詳見 [最終摘要](hardware-handoff-20261108.md)。下方保留量測前制定的協定與準備紀錄。

## 假說與本輪變更

舊 UL-only v2 的 RU 與 main-pool workers 共用 mask，observer 也未固定 CPU。RU 為高優先權 timing thread，可能與 DU workers／observer 產生競爭。v3 測試將這些角色分開是否改善啟動、enqueue delay 與逐秒採集。

這是新資源配置，不能與 v2 混合計算；沒有確認舊問題必然由 RU 搶占造成。guest affinity 不能證明 host physical core 隔離，OS 與其他程序仍可能使用這些 CPUs。

| 角色 | shared | split |
|---|---|---|
| gNB 程序整體允許 CPUs | 0–5 | 0–3 |
| main pool：固定 3 workers | 1–5 | 1–3 |
| RU timing thread | 0 | 0 |
| AI（gate 通過後才執行） | 1–5 | 4–5 |
| observer／其 perf 子程序 | 6–7 | 6–7 |

配置在 `configs/cpu-layout-v3.csv`，由 `scripts/study_layout.py` 驗證。CSV 原文與解析結果進入 fingerprint／context，角色實際 masks、RT policy、observer affinity 逐秒稽核。沒有提供 `--layout-plan` 時維持舊配置，仍因程式版本改變而需要新 baseline。

split 的 AI 只有兩個 logical CPUs，DQN 4 threads 表示在兩 CPU 上四個 intra-op threads，不能稱為四核心負載；此條件事前固定並保留在矩陣報告。兩組 main-pool worker 數保持相同，但允許 CPU 範圍不同，仍須兩組 S0。

## 未調整的標準

- UL-only、5 MHz、1 UE、time_scaling=1，30 秒暖機、60 秒採樣。
- 啟動上限 30 秒；十次全有效；三項跨 run CV≤5%；主要 RT warning 上限 0。
- 只保留原先兩組均只因 RT 失敗時完整重跑 RT≤1 的備援規則。
- 不丟棄首筆、不挑成功 run、不補採漏秒、不提高 RT 權限給 observer／AI。
- 不關閉 RT throttling、不修改 kernel boot options；若這些需要另做實驗，另立協定。
- 兩組同一版本 baseline 通過，才跑原定 CPU DQN 40 attempts；S0 control 失敗立即停。

## 已完成驗證

- 22 項單元／回歸測試通過，包括 CSV 驗證、observer／RU／main-pool／DQN 越界拒絕、舊配置相容性與既有 gate 測試。
- 使用同一個 render_config 產生兩配置，gNB dry-run 皆接受。
- 兩配置實際 gNB 非 RT 程序，各取得五筆符合預期的 worker masks：shared 三 workers=1–5，split 三 workers=1–3，RU=0，observer=6–7。
- smoke 證據在 `builds/v3-smoke/results.json`；sandbox 中 policy=0，所以這只驗證 worker／affinity，不是 RT 或性能驗收。

## 啟動與查詢

在一般 SSH 終端執行一次：

```bash
cd ~/ai-ran-performance
sudo bash scripts/start_baseline_v3.sh
```

建立 tmux session `ai-ran-study-ul-v3`。如果 session 已存在或其他實驗持有鎖，入口會拒絕啟動，不自動刪除原 session。

```bash
python3 scripts/study_status.py
```

手動入口須在 baseline 與 matrix 都加 `--layout-plan configs/cpu-layout-v3.csv`，且相同 config／collector／fingerprint／門檻。預設新 launcher 已代為傳遞，不需自行手動接 matrix。

若仍失敗，保留新批 evidence，先比較：active decoder、RU/worker masks、observer monotonic lateness、CPU pressure、RT 訊息與延遲摘要。即使改善但未達 gate，也仍報告 FAIL，不宣稱已解決全部問題。
