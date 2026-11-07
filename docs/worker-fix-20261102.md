# Worker 數修正（2026-11-02）

已修正明訂 nof_threads 仍被 spare CPU 規則截斷的行為：明訂值限制在 1 至 available CPUs，自動配置維持原邏輯。patch：explicit-worker-count.patch。

使用既有本機 build 的編譯旗標與靜態庫，只重編 worker_manager.cpp 再連結 gNB；不是乾淨來源完整重建。原本 E2 修改仍存在，未宣稱 upstream 官方 binary。

## 驗證

以 configs/du-reduced.yml、pucch-small.yml 啟動真實 gNB 程序，各取得五次 thread snapshots：

| Binary | shared 0–7 | split 0–3 |
|---|---|---|
| 原版 | 3 workers | 1 worker |
| 修正版 | 3 workers | 3 workers |

四種情況全數符合預期；所見 mask 均符合指定 CPU 範圍。原始證據在 builds/worker-fix/smoke/results.json。
13 項既有單元測試通過。sandbox 無 RT 權限，以上只驗證 worker 建立與 affinity，未證明 RT/CV gate 通過。

bin/gnb 已切換修正版；原版保留 bin/gnb-original-20261030，另保留 bin/gnb-worker-fixed。
重建：python3 scripts/build_worker_fix.py；worker 驗證：python3 scripts/verify_worker_fix.py。
run_study.py 會檢查實際三 workers，防止再次靜默改變設計。

## 下一輪實測

在一般 SSH 終端執行（獨立的新 binary 批次，舊 baseline 不可解鎖新矩陣）：

```bash
cd /home/cindy2/ai-ran-performance
sudo bash scripts/start_remote_study.sh --session-name ai-ran-study-fixed
```

先以原雙向工作負載確認修正結果；兩組十次 baseline 通過才進 DQN。保持原 CV/RT 門檻。
如仍失敗，再獨立考慮 UL-only 場景，不混合資料。舊交付驗收 2/4 不變，既有圖不是修正版性能結果。

SHA256（修正版）：`9861634ea5ce5465bb957be09ce12d75329b16620d9ee3384a14aad33dc52840`
