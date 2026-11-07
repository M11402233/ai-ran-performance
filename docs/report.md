> 歷史紀錄：新版 S0 十次 gate、DQN 與完整分核流程見 [study-protocol.md](study-protocol.md)。下列舊結果不是新版實測。

# VM 可行性評估與執行報告

## 結論

這台 VM 能執行 srsRAN 25.10 的 dummy RU / test UE，已實際取得 executor metrics；適合開發配置、採集器及探索 guest 內 CPU 干擾。但目前未通過「可靠且可重複的有效 DU baseline」門檻，不能以這批短版資料完成 RQ1–RQ3 或做正式硬體效能歸因。

8 vCPU／約 16 GB RAM 在本次測試未顯示記憶體容量不足；主要實測問題是部分 runs 沒有有效 decoder 工作、即時處理警告及權限／虛擬化可觀測性不足。不能因此斷言 Xeon 4110 實體硬體效能不足，也不能推論升級 CPU 就能解決。

## 已執行與交付

1. 解讀原 DOCX 並保留文字版；核對計畫的 OCUDU 無硬體測試方向及 srsRAN 安裝文件。
2. 盤點 guest OS、CPU、記憶體、儲存、依賴、GPU 可見性及 profiler 權限。
3. 嘗試從官方 GitHub/GitLab 取得來源，DNS 失敗。找到既有 srsRAN 原始碼／binary，將 binary 複製至 workspace 的 bin/gnb，確認版本、SHA256 與 ldd。
4. 依本機 source CLI schema 建立 10 MHz、1 UE、1T1R dummy RU / no Core 配置，解決低頻寬 PUCCH 資源與 CU-UP 網路需求，成功啟動。
5. 執行 4 種 CPU 條件各 5 次的短版 pilot，保存所有原始資料，產生 CSV、資料品質表與 3 張探索圖。
6. 發現空載 executor 造成零 latency 的陷阱；將沒有持續有效 decoder 活動的 runs 排除比較。更新後續腳本，先等待 active PHY 再開始暖機。

本次使用已有 binary，未從乾淨原始碼重建。原樹存在 E2 KPM 修改，不能將 binary 身分只視為純官方 commit。沒有對外發布或變更系統設定。

## 10 MHz 短版 pilot 實測

20 次 runs 全部正常結束，但只有 15 次通過「採樣所有 decoder interval 均有工作」檢查。

| 條件 | 有效／執行 | enqueue interval mean 的跨 run 平均 ± SD（µs） | 採樣期 RT 警告行數／skip 警告行數（全部 runs） |
|---|---:|---:|---:|
| S0 無背景 | 5/5 | 167.84 ± 21.29 | 261 / 163 |
| S1 低 CPU | 3/5 | 139.69 ± 5.06 | 524 / 555 |
| S2 高 CPU | 3/5 | 144.14 ± 18.31 | 1211 / 925 |
| CPU_BG_PIN 背景限核 | 4/5 | 160.61 ± 12.66 | 685 / 784 |

這些數值是資料品質展示，不能解讀成背景負載讓 DU 變快：有失效樣本／存活者偏差，各組有效工作量也沒有證明相等。警告行數不是標準化 deadline miss 數，也非配對的機制證據。最大 enqueue interval maximum：S0 7677 µs、S1 12295 µs、S2 18416 µs、背景限核 7592 µs，僅是所觀察區間的最大值。

來源：`results/processed/pilot-20261030T131852Z/summary.csv`、`per-run.csv`、`run-quality.csv`。三張圖皆為探索圖，未完成原計畫 IPC 圖或 AI throughput trade-off 圖。

## 5 MHz 補測

另外執行 band 3、5 MHz、SCS 15 kHz、1 UE 的 S0，先確認 active decoder，再暖機 30 秒、採樣 60 秒；僅 1 次，與 pilot 不合併。

59 個完整報告區間都有 decoder 活動；interval enqueue_avg 的平均 87.63 µs，觀察到的 enqueue_max 最大值 13457 µs。採樣期仍有 418 行 Real-time failure 與 220 行 skipped-slot 警告。因此「可持續執行」已驗證，但尚未得到無明顯即時處理警告的 baseline。兩配置採樣長度與 radio 工作量不同，不能將平均值差異當作最佳化效果。

結果：`results/raw/reduced-baseline-20261030T132553Z/`、`results/processed/reduced-baseline-20261030T132553Z/`。

## 各研究問題狀態

| 問題 | 目前證據 | 判定 |
|---|---|---|
| RQ1：AI／CPU 干擾 | 有短版 CPU-only pilot；不是 stress-ng，無 PyTorch AI，且部分 runs 無效 | 未完成；不可將不平衡有效樣本當正式效應 |
| RQ2：瓶頸 | 有 executor delay／context-switch metrics、late/skip 警告；PMU syscall 被拒 | 未完成；不能計算 IPC/cache MPKI 或宣稱 root cause |
| RQ3：改善 | 只有背景負載限核；DU 仍可使用 0–7，沒有 AI progress | 未完成；不是完整分核或 AI throughput trade-off |

零工作 run、暖機、停止過程皆不得被用來聲稱低延遲。原始 1 秒報告的 avg/max 不是 P99。警告行數也不是具明確定義的 deadline miss rate。

## 可行性分級

| 工作 | 此環境 |
|---|---|
| srsRAN 啟動／YAML／log 採集 | 已可行 |
| 固定有效 DU 工作量的長時間重複測試 | 需先修正、重驗 baseline；尚未通過 |
| guest 內 CPU contention 探索 | 可做，但需保留 VM／host 混淆限制 |
| 正式 PMU／cache／IPC 歸因 | 此工作階段不可用，需一般終端或管理員檢查 |
| PyTorch CPU AI | 目前缺套件；網路恢復後可建立小 MLP，不需 GPU |
| CUDA training/inference | 本工作階段看不到 GPU；需另確認 passthrough 與驅動 |
| cgroup cpuset／quota | 此工作階段 mount 唯讀，不可操作 |
| 實體核心隔離／熱與頻率控制 | guest 不能證明；需 host 管理資訊 |
| 真實 UE throughput／RF／P99 | 本 testbed 不涵蓋 |

## 後續的最短路徑

先在 VM 一般終端執行 `python3 scripts/probe.py`，比較 seccomp、loopback、DNS、perf_event_open 結果，避免將 agent sandbox 限制誤認為 VM 本身限制。請勿直接將 perf_event_paranoid 改成全域最低值；依管理需求限制 profiler 權限。

以乾淨固定版本重建 srsRAN 或改用計畫指定的 OCUDU，配置要隨版本重新驗證。初次可用以下依賴清單核對，不需為 dummy RU 購置 SDR：

```bash
sudo apt-get update
sudo apt-get install cmake make gcc g++ pkg-config libfftw3-dev libmbedtls-dev libsctp-dev libyaml-cpp-dev libgtest-dev
sudo apt-get install linux-tools-common linux-tools-generic linux-tools-$(uname -r) stress-ng sysstat python3-venv
```

以上系統安裝指令沒有在受限工作階段執行。正式建置命令與 CMake flags 應依選定版本官方文件，不能直接混用 srsRAN／OCUDU 設定。

先用更新後腳本執行僅 S0：

```bash
python3 scripts/run_matrix.py --conditions S0 --label baseline-validation
```

若 active PHY readiness 失敗，先記錄失敗，不要重試到成功才挑結果。確認不穩定與 host 排程、RT 權限、startup、thread 配置或版本相關前，不展開 AI 矩陣。必要時減少 PUSCH／PDSCH 工作量或縮小頻寬；不同配置要獨立標記，不能混入本批數據。可另以 `time_scaling > 1` 驗證功能，但那是放慢 radio 時鐘，不能稱為 real-time baseline。

穩定後才執行正式 30 秒暖機＋60 秒採樣、每組 5 次；再依計畫加入 CPU PyTorch MLP、測量 AI progress、完整 affinity 對照。若 PMU 仍不可用，將 RQ2 限縮為 guest 排程與 executor 指標；要研究實體 CPU/cache 因果，優先改用 bare metal 或經驗證的 PMU passthrough、host CPU pinning 與資源預留。

## 來源

- 使用者原始計畫：`docs/plan-extracted.txt`。
- srsRAN 官方安裝：https://docs.srsran.com/projects/project/en/latest/user_manuals/source/installation.html
- OCUDU 官方 testmode：https://docs.ocudu.org/tutorials/testmode/
- 版本相符配置依據：本機 source 的 `configs/testmode.yml`、`configs/cell_cfg_pucch_5_mhz_bw.yml`，以及 executor metrics／CU-UP CLI schema。

本報告是實測可行性紀錄，非原計畫要求的完整八週研究或 8–12 頁最終研究報告。
