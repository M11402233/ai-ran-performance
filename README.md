# AI–RAN：DU baseline、AI 共置干擾與 CPU／CUDA 資源取捨

本專案研究 srsRAN DU 與 AI 工作共用一台主機時的效能干擾，並評估 CPU 分核、AI concurrency 限制及後續 CUDA offload 的代價。使用 dummy RU／test UE 產生合成 DU 工作負載，先驗證 DU-only baseline，再執行 AI 共置比較。

**最新狀態（2026-11-08 更新）：UL-only v3 已結束，20 次中 19 次量測有效，shared／split baseline 仍均未通過；尚無正式 DQN 矩陣或 CUDA 實驗。驗收為 2／4 通過。**

新機器的環境安裝、CUDA 實作與研究交接見 [GPU_HANDOFF_PLAN.md](GPU_HANDOFF_PLAN.md)。該文件是後續計畫，不代表 GPU／FlexRIC 閉環已完成。

## 目前結論：baseline 未過，不代表必須使用 GPU

目前證據只支持：**這台 KVM VM 在已測試的雙向與 UL-only 配置下，尚未符合預先設定的 baseline 穩定性與 RT 門檻。**

- 已確認三個 main-pool workers 與 RT policy 生效，CPU PMU 可讀；這些問題已不能單獨解釋剩餘失敗。
- 降低 DL 負載後，decoder 偶發未啟動、split 採集長停頓與 RT 警告仍存在。精確根因尚未確認，不能據此宣稱這台硬體永遠無法通過。
- 失敗發生於 **沒有 AI 負載** 的 DU-only 階段。加上 GPU 並不會自動修復 DU 的 CPU 排程、RU timing、RT throttling 或 host 資源競爭問題。
- 下一步優先驗證可控的 CPU／排程環境，最好是專用實體 Linux 主機；沒有 GPU 的可控主機也能繼續驗證 baseline。
- 若換到 GPU 主機，先重新建立該主機的 DU-only baseline。CUDA 是新增的 AI offload 比較軸，不是通過 baseline 的必要條件，也不是保證通過的方法。

目前不放寬門檻、不挑成功 runs 解鎖 DQN；也不以跨主機的數值差異直接宣稱 GPU 效果。

## 實驗版本紀錄

下表是實驗階段紀錄，並非 Git release tags。不同 binary、配置與協定的資料分批保留，不混合計算。

| 日期／階段 | 工作內容 | 結果與限制 |
|---|---|---|
| 10/30：10 MHz pilot | 無背景、低／高 CPU、背景限核，各 5 次 | 20 次中 15 次 decoder 持續有效；有空載與樣本不平衡，只作可行性探索 |
| 10/30：5 MHz 單次補測 | 1 UE，30 秒暖機、60 秒採樣 | 59 個完整 decoder intervals；enqueue_avg 平均約 87.63 µs，仍有 418 行 RT 訊息 |
| 10/30：原版正式 baseline | shared／split 各 10 次 | 量測有效 10/10、9/10；gate 均 FAIL。後續發現兩組實際 worker 數為 3／1，存在混雜因素 |
| 11/2：worker 修正 | 修正明訂 worker 數仍受 spare-CPU 規則截斷 | 真實程序確認 shared／split 均建立 3 workers；原版保留備份 |
| 11/7：修正版 UL+DL | 兩組各 10 次，實際三 workers | 最終稽核有效 9/10、7/10；gate 均 FAIL，未進 DQN |
| 11/7：採集器 v2 | monotonic 排程、禁止漏秒補採、runtime／收尾共用 audit | 新增診斷紀錄與回歸測試；17 項測試通過 |
| 11/7：UL-only v2 | PUSCH 開、PDSCH 關，兩組各 10 次 | 有效 9/10、8/10；gate 均 FAIL，未進 DQN；本輪已收尾 |
| 11/7：baseline v3 | RU 固定 CPU 0、observer 固定 6–7、main pool 分離 | 有效 10/10、9/10；shared CV/RT 未過，split 有 8.07 秒漏採；gate 均 FAIL |
| 待執行：新主機 CPU／CUDA | 新主機 baseline、同機 CPU／CUDA AI 對照、後續 FlexRIC | 仍屬計畫；CUDA runner 與 GPU metadata／分析尚待實作 |

歷史報告：[初期試跑](docs/report.md)、[原版 baseline 排查](docs/baseline-diagnosis-20261031.md)、[worker 修正](docs/worker-fix-20261102.md)、[採集器 v2 與 UL-only 協定](docs/next-round-ul-v2.md)。歷史文件的「尚未量測／無 PMU」敘述保留當時狀態，最新進度以本 README 與指定批次紀錄為準。

## Baseline v3：已完成且未通過

已依 [v3 資源配置協定](docs/baseline-v3.md) 完成正式重測，有效 19/20，但兩組 gate 仍未通過；最新分析與硬體接手順序見 [硬體交接摘要](docs/hardware-handoff-20261108.md)。

| 角色 | shared | split |
|---|---|---|
| DU main pool（兩組皆 3 workers） | CPU 1–5 | CPU 1–3 |
| RU | CPU 0 | CPU 0 |
| observer | CPU 6–7 | CPU 6–7 |
| gate 通過後的 AI | CPU 1–5 | CPU 4–5 |

**新機改用 v4**：[baseline-v4.md](docs/baseline-v4.md)、`configs/cpu-layout-v4.csv`、`scripts/start_baseline_v4.sh`。兩組 DU 配置相同，只改 AI 位置；共 35 項測試通過。

配置檔：[cpu-layout-v3.csv](configs/cpu-layout-v3.csv)。22 項測試與非 RT affinity smoke 通過；正式重測也已完成。shared 10/10、split 9/10 有效，shared 延遲尖峰 CV 與 RT 未過，split 仍有約 8.07 秒採集停頓。CV／RT 門檻維持原規則。

```bash
cd ~/ai-ran-performance
sudo bash scripts/start_baseline_v3.sh
```

此輪與 v2 的資源配置不同，必須重新跑兩組各十次 baseline；不能拿舊批資料解鎖。

## 前一輪結果：UL-only v2

Session：`remote-session-20261107T212225Z`；狀態：`stopped`，原因是 baseline gate 未通過，並非矩陣完成。`perf_event_paranoid` 已由流程恢復原值。

配置：5 MHz、1 test UE、PUSCH active、PDSCH inactive、`time_scaling=1`；固定 3 main-pool workers、30 秒暖機、60 秒採樣。

| 指標 | shared | split |
|---|---:|---:|
| 已嘗試 | 10 | 10 |
| 證據有效 | 9 | 8 |
| 無效比例 | 10% | 20% |
| 各有效 run 的每秒 enqueue_avg 中位數範圍 | 100–108 µs | 1,885–3,466 µs |
| 各有效 run 的 RT warning 峰值範圍 | 23–54 行／秒 | 114–201 行／秒 |
| CPU generic cache miss rate | 21.56–24.54% | 19.76–21.07% |
| IPC | 0.871–0.911 | 0.962–0.995 |
| baseline gate | FAIL | FAIL |

「量測有效」表示採樣與工作負載證據完整，不代表符合 RT／穩定性門檻。上表只作描述性診斷，不是完成正式分核因果比較的證明。

無效原因與新增證據：

- shared 最後一次在 30 秒內沒有 active decoder。失敗不只出現在第一筆，不能單純丟棄首筆解決。
- split 第 4、10 次採集分別出現約 4.257、16.874 秒的 monotonic lateness，新腳本即時判無效，沒有用補採填補缺秒。
- wall 與 monotonic 同時落後，不能用單純 wall-clock 校正解釋。CPU PSI 偏高，支持優先排查排程競爭；仍不能確認是哪個程序、RT throttling 或 host 行為造成。
- 兩組因有無效 run，三項 baseline CV 未計算；報表中的 `None` 不是已實測三項 CV 全部超標。

### PMU 狀態

**CPU PMU 已讀到實際數字**，事件為 `cache-references`、`cache-misses`、`instructions`、`cycles`。本輪 17 個有效 run 已納入 PMU 彙整。

失敗／中止 run 的 perf 可能缺少事件；不以零代替，也不納入有效性能比較。計數器是否可用與整個 run 是否有效分開判斷。generic cache 事件不等於特定 L1／L2／LLC 事件，亦不能直接證明 cache 是根因。

## 驗收門檻與量測範圍

四項交付驗收目前為：

- [ ] 至少一組符合協定、可重複的 DU-only baseline。
- [x] 有效 DU 工作負載與完整量測紀錄。
- [ ] 完成正式 shared／split AI 共置比較。
- [x] 產生解釋結果與限制的圖表。

Baseline 要求每 layout 十次全有效，三項延遲摘要的跨 run CV≤5%，預設每秒 RT 訊息上限 0。僅在兩組都全有效、CV 全過且只因 RT 失敗時，允許依預先規則以 RT≤1 各完整重跑一次；本輪不符合此備援條件。

這是工程 gate，不是統計功效保證。Baseline PASS 也只代表同一批次條件下的重複性，不能推廣成跨日／跨主機保證。

舊協定的 DU 與 DQN 配置是 shared 雙方 CPU 0–7；split DU 0–3、DQN 4–7。v3 改用上方 CSV 角色配置。CPU DQN 使用 1／2／4 intra-op threads，記錄 minibatch optimizer updates/s。這些 CPU mask 是舊 VM 的協定，新主機必須先核對 cpuset、physical cores、SMT／NUMA；不能直接照搬成實體隔離證據。

沒有真實 UE／Core／RF throughput、逐任務 P99 或 host 實體核心隔離的量測證據。合成 DQN 不是已部署的 RAN 控制器。

## 查閱成果與重現入口

先讀 [最新驗收報告](deliverables/completion.md)，搭配 [總覽圖](deliverables/overview.png)、[PMU 圖](deliverables/cache-overview.png)、[圖說](deliverables/caption.md)、[所有 runs](deliverables/all-runs.csv) 與 [PMU 彙整](deliverables/perf-summary.csv)。

單一交付檔為 `deliverables/du-dqn-study.zip`，包含程式、配置與彙整成果；raw logs／JSON／JSONL 留在量測主機供稽核，不逐筆附入 ZIP。`deliverables/` 指向最新收尾批次，先前版本保留於 `results/processed/remote-session-*/`。

查詢最新批次，不會啟動新實驗：

```bash
python3 scripts/study_status.py
```

以下是既有入口，**不要在未修正環境或未訂新方案時反覆重跑相同失敗配置**：

- 一般終端、sudo／tmux 自動流程：`scripts/start_remote_study.sh`。
- UL-only v2 入口：`scripts/start_next_study.sh`；使用固定 session 名稱，重複啟動會被拒絕。
- 手動 baseline／matrix：`scripts/host_study.sh`；matrix 會重查兩組 baseline、context 與 fingerprint。
- 舊 `run_matrix.py`／`run_perf.sh` 與 CPU arithmetic 結果只供歷史重現。

完整協定見 [study-protocol.md](docs/study-protocol.md)、[remote-study.md](docs/remote-study.md) 與 [completion-criteria.md](docs/completion-criteria.md)。

Agent sandbox 的 `NoNewPrivs=1`／零 capabilities 可能阻擋 sudo，需由一般 SSH 終端啟動具權限的量測。這不代表主機缺 perf 或 PyTorch；一般主機流程已成功執行 PMU 採樣。Python runner／AI 維持 SCHED_OTHER，gNB 自行設定 RT。

## 下一階段

1. 保留這三批 baseline 的失敗證據與環境差異，不再以更寬門檻重試至通過。
2. 優先在可控 CPU 環境驗證 DU baseline，並排查 RU／worker／observer 的排程、RT throttling、host pinning／超額配置與啟動失活；目前尚無單一根因證明。
3. 有 GPU 時，在**同一台新主機**加入 CPU／CUDA DQN 對照；先完成 CUDA runner、版本鎖與資料 schema，再凍結版本重測 baseline。
4. FlexRIC／KPM monitoring 與 CUDA xApp 另列階段；尚未證明端到端監控／控制閉環完成。

新主機詳細安裝、版本核對、實驗矩陣與 Codex 接手提示詞均在 [GPU_HANDOFF_PLAN.md](GPU_HANDOFF_PLAN.md)。

## 程式與來源版本

目前基於 srsRAN Project 25.10.0，upstream commit `d2f4b70dda8e2c557d5b05a0ac5f92dbddda19bc`，另有明訂 worker 數修正。舊來源 E2/KPM 變更保留於 [existing-source.patch](docs/existing-source.patch)；worker patch 見 [explicit-worker-count.patch](docs/explicit-worker-count.patch)。

舊 VM 的修正版為既有本機 objects／libraries 增量重編與連結，未宣稱乾淨來源全量重建，也未宣稱已改用 OCUDU。新機應 pinned source 重新建置，記錄 patches／flags／binary SHA256，不搬 `-march=native` binary 代替新主機建置。AGPL license 見 [docs/srsran-LICENSE](docs/srsran-LICENSE)。

`bin/`、`builds/`、`results/`、虛擬環境與 ZIP 不在一般 Git 交付範圍；新 clone 必須建置 binary，完整 raw 證據需另外移轉。未提交的本機檔案也不會自動出現在 GitHub。

## 開發檢查

```bash
python3 -m unittest discover -s tests -v
```

最近一次 v3 腳本修正後 22 項測試通過；這是程式回歸測試，不是 baseline／CUDA 性能驗收。
