# 遠端自動執行（啟動前固定規則）

本規則在新量測開始前寫入程式；不依結果挑 N。第一次嘗試實際尚未啟動，因 agent 的 sudo 被 NoNewPrivs 擋住。

- 最小關注延遲效應 20%，三項 baseline latency 摘要的跨 run CV 均 ≤5%。
- shared 與 split 各十次，primary RT 上限每秒 0 行。
- 兩批通過才執行 DQN 矩陣，0／1／2／4 intra-op threads × 兩種配置 × 五次。
- **唯一自動備援**：兩批都只因 RT 訊息上限失敗，且各十次全部有效、CV 全過，才將上限改為每秒 **1 行**，兩批各完整重跑十次。
- 備援保留原批，兩批新資料都通過才接受；CV／有效性門檻不放寬，不混用 primary 與 fallback baseline。
- 任一批有無效 run、CV 不合格、只有一批失敗，或備援仍失敗，立即停止，不進矩陣、不再改 N。
- 矩陣中 S0 control 失效／RT 超標立即停止，未執行條件明列於品質表。

N=1 是事先選定的工程容忍值，非「已證明可接受的 radio deadline miss rate」。統計的是 FAPI 訊息行數；每秒至多一行仍可能表示持續的即時問題，報告需明確揭露。

## 啟動

在一般 SSH 終端執行一次，需 sudo、python3-venv、tmux、符合 guest kernel 的 perf/linux-tools。腳本不自動安裝 OS 套件：

```bash
cd /home/cindy2/ai-ran-performance
sudo bash scripts/start_remote_study.sh
```

腳本會建立 root 的 `ai-ran-study` tmux session，在其中準備 `.venv-study`／Python 依賴、檢查硬體 perf 計數器，再依固定規則量測。沒有硬體 PMU 就停止，**不自動切成 scheduling-only**；要採用 proc 模式，需另依 study-protocol.md 明訂一批獨立實驗。

```bash
sudo tmux attach -t ai-ran-study
# 只離開畫面、繼續跑：Ctrl-b，再按 d
# 停止量測：attach 後 Ctrl-C，讓流程清理並恢復 paranoid
# 查看輸出：
tail -f results/processed/remote-console.log
```

設定 paranoid 前記錄原值，整個批次維持 1，最後嘗試恢復。root tmux 避免中途 sudo timestamp 過期。不要另開其他同時量測的腳本。VM 斷電或強制 SIGKILL 無法保證清理，需手動檢查 sysctl 與程序。

總時長取決於每次啟動；通常應預留約 2–3 小時。若觸發完整備援，另加約 30–40 分鐘。網路下載依賴、baseline 不穩、啟動逾時可能讓估算偏離。主機前檢查失敗時不會假裝已開始兩小時量測。

每個 stage 的 log、預先方案與狀態保留於 `results/processed/remote-session-時間/`；失敗／完成後都嘗試產出 `deliverables/du-dqn-study.zip`。ZIP 含 code、方案、狀態、彙整 CSV 與圖，不含逐筆 JSON／JSONL／raw logs。合成測試資料不會混入結果。
