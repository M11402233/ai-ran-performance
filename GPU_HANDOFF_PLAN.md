# AI–RAN：GPU 主機移轉與 CUDA 實驗交接計畫

建立日期：2026-11-07（UTC）。對象：使用者與新 GPU 主機上的 Codex。

> 新機器 Codex：請先完整讀取本檔，再讀專案 README 與適用的 AGENTS.md。這份文件是待執行計畫，並非已完成 GPU 實驗的報告。先盤點實際環境、核對最新紀錄，依階段執行並更新交接狀態；不要直接啟動舊矩陣。

## 1. 實驗目的與研究範圍

專案名稱：AI–RAN Performance Interference and Resource Optimization on Commodity Hardware。

研究同一主機上 DU 與 AI 工作共置時的資源競爭，以及分核、限制 AI CPU concurrency、CUDA offload 的取捨：

1. **RQ1：干擾**。固定 DU 工作量時，CPU AI／CUDA AI 是否改變 DU executor 的 queueing latency、task duration 與 RT 訊息？
2. **RQ2：機制**。差異較符合 CPU 排程、計算飽和、cache／memory 行為、資料傳輸或 GPU 提交／同步開銷中的哪些解釋？需控制實驗，不先指定答案。
3. **RQ3：改善成本**。分核或 GPU offload 能否改善 DU，同時維持 AI 的 optimizer updates/s 或 inference/s？
4. **延伸：RIC 開銷**。加入 FlexRIC／KPM xApp 後，監控本身造成多少負擔？進一步控制閉環另列階段。

主線是 **CPU 上的 srsRAN DU + CUDA 上的 AI**。把 DQN 搬到 CUDA 不會自動把 srsRAN PHY／DU 搬到 GPU；cuBB、Aerial 或 GPU PHY 是不同系統整合專案，不在本輪主線。

採用 ru_dummy + test UE + no_core 的合成 DU 計算負載；第一階段不需要 SDR、真實 UE、5GC。沒有端到端路徑時，不宣稱量到 UE user-plane throughput、真實 RF 效能或 BLER。每秒 executor avg/max 不能稱為逐任務 P99；RT warning 行數不能稱為唯一 deadline miss 數。

## 2. 專案位置與交接完整性

- GitHub：<https://github.com/M11402233/ai-ran-performance>
- 舊機工作目錄：`/home/cindy2/ai-ran-performance`。
- 新機可以使用其他路徑，腳本應以 repo root 推導路徑。
- 文件建立時，本機 `main` 最新已知 commit 是 `568adfc`，但後續腳本修正、成果與本文件仍有未提交內容；**不要假設只 clone 這個 commit 就包含本交接內容**。
- `bin/`、`builds/`、`results/`、虛擬環境及 ZIP 被忽略，不會隨一般 Git clone 帶到新機。歷史 CSV／圖在 `deliverables/`；若要完整稽核，另搬 raw records 並保留目錄結構。
- 新機收到資料後先執行 `git status --short --branch`、`git log -3 --oneline`，確認下列必要檔案實際存在。缺檔時先補交接，不用舊程式冒充新版。

| 檔案 | 用途／注意事項 |
|---|---|
| `scripts/run_study.py` | CPU baseline／矩陣 runner，包含三 worker 檢查、monotonic sampling；尚無 CUDA 條件 |
| `scripts/study_metrics.py` | interval parser、逐秒 thread audit、baseline gate |
| `scripts/perf_cache.py` | 四項 CPU PMU 事件與 coverage 檢查 |
| `scripts/remote_study.py` | 固定 gate 與備援規則的自動流程；目前只會跑 CPU DQN |
| `scripts/start_remote_study.sh` | 一般 SSH／sudo／tmux 啟動入口 |
| `scripts/start_next_study.sh` | 舊機下一輪 UL-only 入口，不是 GPU 自動流程 |
| `scripts/study_status.py` | 唯讀進度查詢 |
| `workloads/dqn_train.py` | CPU-only 合成環境 DQN，不是現成 xApp／RAN 控制器 |
| `configs/du-reduced.yml` | 5 MHz、1 UE、UL+DL 場景 |
| `configs/du-uplink-only.yml` | 獨立 UL-only 場景，不能與 UL+DL 混算 |
| `configs/pucch-small.yml` | 小頻寬 PUCCH 配置 |
| `docs/explicit-worker-count.patch` | 修正明訂 worker 數仍被 CPU 預留規則截斷 |
| `docs/existing-source.patch` | 舊來源的 E2/KPM 修改證據，不是新機預設必套 patch |
| `tests/test_sampling.py` | 漏秒、時鐘變化、worker 稽核與 gate 一致性的回歸測試 |
| `analysis/build_outcome.py` | 四項驗收與總覽／PMU 圖 |

## 3. 已完成進度與已知問題

### 3.1 舊環境

KVM VM，8 vCPU、約 16 GB RAM，Intel Xeon Silver 4110 的 guest CPU 標示，Ubuntu kernel 5.15 系列。guest vCPU 不代表已隔離的 host 實體核心；CPU steal 很低也不能證明沒有 host 排程干擾。

既有 srsRAN 版本 25.10.0，來源 commit：

`d2f4b70dda8e2c557d5b05a0ac5f92dbddda19bc`

舊來源有未提交 E2/KPM 修改。修正版 binary 使用既有本機 objects／libraries 增量重編及連結，**未完成乾淨來源全量重建**。新主機應重新建置，不搬舊 `-march=native` binary 當正式版本。

### 3.2 歷史實驗摘要

| 階段 | 結果 | 可以得出的結論 |
|---|---|---|
| 10/30，10 MHz CPU-only pilot | 20 次中 15 次有持續 decoder 活動 | 測試鏈可運作；有空載與樣本不平衡，不能當正式干擾效應 |
| 10/30，5 MHz 單次補測 | 59 個完整 decoder intervals；enqueue_avg 平均約 87.63 µs；418 行 RT 訊息 | 可產生有效 DU 工作，但即時性未過關 |
| 10/30，兩配置各十次 baseline | shared 10/10、split 9/10 量測有效；兩組 gate FAIL | 未進 DQN；PMU 成功；之後發現 worker 數不同 |
| 11/2，worker 修正 | 原版 shared=3、split=1；修正版實際兩組皆=3 | 解決一個重要混雜因素，未證明效能穩定 |
| 11/7，修正版 UL+DL baseline | shared 9/10、split 7/10 經證據稽核有效；兩組 gate FAIL | 沒有 DQN 矩陣；不能宣稱正式分核比較完成 |

修正版 UL+DL 的有效 run 範圍：

| 指標 | shared | split |
|---|---:|---:|
| 每個 run 的每秒 enqueue_avg 中位數 | 89–93 µs | 1,745–4,587 µs |
| 各 run 的 RT 訊息峰值 | 14–64 行／秒 | 156–213 行／秒 |
| CPU generic cache miss rate | 16.09–24.65% | 15.57–18.05% |
| IPC | 0.973–0.994 | 0.964–1.093 |

這些是失敗 baseline 的描述性診斷，不是 GPU 結果，也不是分核因果證明。

### 3.3 PMU 並非不可用

舊機一般 root SSH 流程成功讀到 `cache-references,cache-misses,instructions,cycles`；上一輪已完成採樣的四事件 running coverage 都為 100%，沒有 `<not supported>`／`<not counted>`。早期文件所寫「缺 perf／無 PMU」是當時 agent sandbox 的歷史狀態，不代表之後主機沒有數據。

新主機必須重新檢查 PMU；generic cache 事件不能直接當成 L1/L2/LLC 分層事件，CPU PMU 也不是 GPU counter。

### 3.4 已定位並修正的腳本問題

- gNB 的 worker 自動 sizing 即使讀到明訂值，仍套用「預留 3 CPU」上限；split mask 只有 4 CPUs 時變成一個 worker。patch 已改成明訂值在可用 CPU 數內直接生效。
- 舊採集器 split 有兩筆停頓，造成 2／10 秒缺漏，醒來後同一秒連續補採。CPU ticks 也增加，較支持實際停頓；精確根因未定。
- 新版使用 monotonic deadlines，加上 wall-clock 秒完整性，漏秒立即失敗；runtime gate 與收尾共用 audit。
- 新版保留 `/proc/stat`、CPU/I/O/memory PSI、observer schedstat/io、RT runtime/period 等診斷。
- readiness 檢查最新 decoder report 的 executed 或 deferred 是否大於零。啟動上限仍為 30 秒，不丟棄首筆、不重試至成功。
- 已有 17 項單元／回歸測試通過；這不是 RT 穩定性或 CUDA 功能驗收。

### 3.5 正在進行的 UL-only 批次：只是一個快照

文件建立時新一輪為 `remote-session-20261107T212225Z`，使用 `configs/du-uplink-only.yml`，稽核版本 2。建立文件時仍在 baseline 階段，**本檔不預填最終 PASS**。

最後核對快照：2026-11-07 21:38:50 UTC；session=`remote-session-20261107T212225Z`，status=`primary-baselines`；baseline shared: 10 筆已收尾；baseline split: 0 筆已收尾。此快照不表示 gate 通過。

接手時先讀最新 `results/processed/remote-session-*/status.json`、`deliverables/completion.md`，或執行 `python3 scripts/study_status.py` 更新狀態。若只收到 GitHub 而沒收到 raw data，需明確記錄「尚未取得本批原始證據」。

### 3.6 UL-only v2 最終結果（後續補記）

`remote-session-20261107T212225Z` 已結束，status=stopped，兩組 baseline gate FAIL；20 attempts 中 17 筆經證據稽核有效，未進入 DQN。sysctl 已恢復。

| 指標 | shared | split |
|---|---:|---:|
| 有效／嘗試 | 9/10 | 8/10 |
| 每 run 的每秒 enqueue_avg 中位數範圍 | 100–108 µs | 1885–3466 µs |
| 有效 run 的 RT 峰值範圍 | 23–54 行/秒 | 114–201 行/秒 |
| cache miss rate | 21.56–24.54% | 19.76–21.07% |
| IPC | 0.871–0.911 | 0.962–0.995 |

shared repeat=9 仍沒有 active decoder；問題不是只出現在第一筆。split repeat=3/9 因 monotonic lateness 約 4.257/16.874 秒被新採集器即時判無效。wall 與 monotonic 同時落後，因此不能用單純 wall-clock 校正解釋。沒有補採掩蓋失敗。

兩個失敗 split run 的前後 CPU PSI some avg10 約 55–62%，IO PSI avg10=0；這支持追查 CPU 排程競爭，但不能確認由某個程序或 RT throttling 導致。觀察到 RT runtime/period=950000/1000000 µs，只是設定證據，不是已發生 throttling 的證明。

UL-only 沒有解決穩定 gate，不能宣稱減少 DL 即可穩定。新主機接手時優先驗證裸機 CPU/RT baseline、RU/worker/observer 排程與拓撲，不在舊 VM 反覆放寬門檻。

### 3.7 v3 腳本已準備（尚未正式重測）

新增 `configs/cpu-layout-v3.csv` 與 `scripts/study_layout.py`，資源配置已外部化；詳見 `docs/baseline-v3.md`。RU=0、observer=6–7；shared main pool=1–5、split=1–3，兩組均三 workers。程式已通過 22 項測試與非 RT mask smoke，不能當成 RT gate 通過。

新機先檢查這份 CSV 是否符合實際 topology／cpuset，不照搬 logical CPU 編號；下方舊「硬編碼」說明指未提供 plan 的 legacy 模式。

## 4. 新 GPU 主機的環境決策

優先使用可直接開機的 Ubuntu 22.04／24.04 LTS x86-64 與獨立 NVIDIA GPU；實際組合依 GPU、驅動、PyTorch 與 RAN 版本相容性決定。這是建議選型，不是已驗證所有組合相容。

- 建議可用 RAM 至少 16 GB，32 GB 較便於建置；預留 SSD 約 60–100 GB 作來源、依賴、建置與 raw logs。這是工程預算，不是模型最低需求。
- 不預設 GPU 型號或顯存。先盤點 compute capability，再選支援該架構的 CUDA／PyTorch wheel；不能只追最新。
- 先驗證 CPU topology、RT 與 PMU，再跑 AI。WSL／一般共享 VM 可作功能驗證，正式排程結論須揭露其限制。
- 原 runner 硬編碼 CPU 0–7 與 split 0–3／4–7。新機若 CPU 數、cpuset、SMT／NUMA 不同，**先改成外部 layout plan 並更新 audit／fingerprint，不能直接照跑**。
- 4 個 physical cores + SMT 不等同 8 個獨立核心。若 DU／AI 分到 sibling threads，必須明示，不能宣稱實體分核。
- gNB main pool 固定 3 的設計若新硬體不適合，先訂新協定再跑兩配置完整 baseline，不能拿舊結果解鎖。

新機需產出 `docs/gpu-host-inventory.md`，至少包含：

```bash
uname -a
cat /etc/os-release
lscpu
lscpu -e=CPU,CORE,SOCKET,NODE,ONLINE
taskset -pc $$
free -h
df -h .
lspci -nn
nvidia-smi
nvidia-smi topo -m
cat /proc/sys/kernel/perf_event_paranoid
cat /proc/sys/kernel/sched_rt_runtime_us
cat /proc/sys/kernel/sched_rt_period_us
```

另記錄 BIOS／SMT、governor、頻率／溫度、GPU UUID／顯存／driver、虛擬化、cpuset、Secure Boot 狀態與背景服務。無法讀取的欄位寫 unavailable，不填推測值。

## 5. 空機器安裝清單與順序

先盤點既有環境；以下是 Ubuntu 套件範例，依實際 release 核對。文件建立本身不代表已安裝新主機套件。安裝權限沿用使用者當次授權；遇到 sandbox 權限限制，整理一個一般 SSH 終端入口，不循環嘗試升權。

| 類別 | 軟體 | 階段 |
|---|---|---|
| 基礎 | Git、CMake、GCC/G++、pkg-config、tmux、Python venv | 必要 |
| RAN | srsRAN Project、FFTW、mbedTLS、SCTP、yaml-cpp、gtest | 必要 |
| 量測 | 對應 kernel 的 perf、sysstat、numactl、stress-ng、lm-sensors | 必要／診斷 |
| GPU | NVIDIA driver、CUDA-enabled PyTorch | CUDA 主線必要 |
| CUDA 開發 | CUDA Toolkit／nvcc、Nsight Systems／Compute | 自訂 kernel／深度 profiling 時加入 |
| RIC | FlexRIC、SWIG、libconfig、SCTP、Python headers | E2／xApp 階段；主線 baseline 不啟動 RIC |
| 網路延伸 | ZeroMQ、srsUE、Open5GS、UHD／SDR | 真實／模擬端到端路徑才需要 |

### 5.1 Ubuntu 基礎套件

```bash
sudo apt-get update
sudo apt-get install -y \
  git build-essential cmake ninja-build pkg-config ccache \
  curl wget ca-certificates unzip tmux \
  python3 python3-dev python3-venv python3-pip \
  libfftw3-dev libmbedtls-dev libsctp-dev libyaml-cpp-dev libgtest-dev \
  linux-tools-common linux-tools-generic sysstat numactl stress-ng lm-sensors
sudo apt-get install -y "linux-tools-$(uname -r)"
```

若 exact-kernel tools 套件不存在，先核對 kernel 來源與可用工具版本；不要把 perf 命令存在當成 PMU 驗收。[srsRAN 安裝文件](https://docs.srsran.com/projects/project/en/latest/user_manuals/source/installation.html)

### 5.2 NVIDIA driver

先跑 `nvidia-smi`。若已有可用且相容的驅動，不為本計畫任意覆寫。空 Ubuntu 主機可先查看發行版建議：

```bash
sudo apt-get install -y ubuntu-drivers-common
ubuntu-drivers devices
```

依硬體與 Ubuntu 官方方式選擇 desktop／server 驅動；可用的自動安裝路徑為 `sudo ubuntu-drivers install`。記錄所選版本；若需要重開機，交接狀態後由使用者安排，不在正在量測的主機中重開。回來後以 `nvidia-smi` 再驗證。[Ubuntu 驅動安裝](https://ubuntu.com/server/docs/how-to/graphics/install-nvidia-drivers/)

### 5.3 Python／PyTorch 與 CUDA

先建立專用 venv。Python minor version 要與所選 PyTorch wheel 相容，不能假設 Ubuntu 的預設 Python 永遠支援最新 PyTorch。

```bash
python3 -m venv .venv-study
.venv-study/bin/python -m pip install --upgrade pip
```

由新機 Codex 在 [PyTorch 官方選擇器](https://pytorch.org/get-started/locally/)／previous versions 頁核對：OS、Python、GPU 架構、driver、可用 CUDA wheel。先把**確定的安裝指令與版本**記入 `docs/gpu-environment-lock.md` 再安裝；不要原樣執行含佔位符的指令，也不要直接用舊 `requirements-study.txt` 的寬鬆範圍當 GPU 版本鎖。

先安裝選定的 CUDA-enabled torch，再安裝 pandas／matplotlib 等分析依賴。torchvision／torchaudio 不是目前小型 DQN 的必要依賴。完成後保存：

```bash
.venv-study/bin/python -m pip freeze > requirements-gpu-lock.txt
.venv-study/bin/python -m torch.utils.collect_env > docs/torch-environment.txt
```

PyTorch CUDA wheel 的執行依賴與系統 Toolkit／nvcc 是不同層次。使用預編譯 PyTorch 跑張量通常不需要先安裝完整 Toolkit；需要自訂 CUDA extension 或編譯 CUDA C++ 時，再依 [NVIDIA Linux 安裝指南](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/) 安裝對應 Toolkit。記錄 driver、`torch.version.cuda`、`nvcc --version` 三者；`nvidia-smi` 的 CUDA 標示不等於已安裝的 Toolkit 版本。

最低 GPU smoke test（先離線執行，不與 DU baseline 同時跑）：

```bash
.venv-study/bin/python - <<'PY'
import torch
assert torch.cuda.is_available(), 'CUDA unavailable: inspect wheel, driver and GPU architecture'
print('torch', torch.__version__, 'runtime', torch.version.cuda)
print('GPU', torch.cuda.get_device_name(0))
print('capability', torch.cuda.get_device_capability(0))
x = torch.randn(256, 256, device='cuda', requires_grad=True)
loss = (x @ x.T).square().mean()
loss.backward()
torch.cuda.synchronize()
assert torch.isfinite(loss).item()
print('CUDA allocation / matmul / backward: PASS')
PY
```

### 5.4 srsRAN：新機乾淨來源建置

先以已知版本延續研究，避免同時更換 RAN stack 與 AI device。原計畫曾提 OCUDU，**實際歷史測試使用的是 srsRAN Project**；如果選擇 OCUDU，需另建場景、重驗 YAML 與 metrics parser，不能改名稱就沿用結果。

在 repo root 的同一個一般終端 session 執行以下範例。`third_party/` 是外部來源目錄，加入 `.gitignore`，不要巢狀提交整個 upstream repository。

```bash
PROJECT_ROOT="$PWD"
mkdir -p third_party bin
git clone https://github.com/srsran/srsRAN_Project.git third_party/srsRAN_Project
git -C third_party/srsRAN_Project checkout d2f4b70dda8e2c557d5b05a0ac5f92dbddda19bc
git -C third_party/srsRAN_Project apply --check "$PROJECT_ROOT/docs/explicit-worker-count.patch"
git -C third_party/srsRAN_Project apply "$PROJECT_ROOT/docs/explicit-worker-count.patch"
cmake -S third_party/srsRAN_Project -B third_party/srsRAN_Project/build \
  -DCMAKE_BUILD_TYPE=Release
cmake --build third_party/srsRAN_Project/build --target gnb -j2
cp third_party/srsRAN_Project/build/apps/gnb/gnb bin/gnb
bin/gnb --version
ldd bin/gnb
sha256sum bin/gnb
```

如 upstream 取不到該 commit，先取得舊來源快照或選定可驗證替代 revision 並記錄差異；不要靜默切到最新 main。patch 不適用則檢查該版 sizing 是否已修正，不能忽略錯誤。CMake flags 依 pinned revision 核對；小記憶體主機先用 `-j2`。

**不預設套用 `docs/existing-source.patch`**：它修改 E2/KPM granularity 欄位行為，並非 DU baseline 必要修正；若後續確有互通需求，另行審查與驗證。記錄 clean upstream SHA、所有 patches、build options、compiler 與 binary SHA256，保留 AGPL license。

`scripts/build_worker_fix.py` 是舊機增量重連工具，內含舊機絕對路徑，不能拿來取代新機全量建置。

先做 YAML dry-run：

```bash
bin/gnb --dryrun -c configs/du-uplink-only.yml -c configs/pucch-small.yml
.venv-study/bin/python -m unittest discover -s tests -v
```

真正啟動後仍需檢查三個 main-pool workers、RU、各 thread 的實際 mask 與 RT policy；dry-run 通過不代表即時性通過。

### 5.5 FlexRIC 與 E2：獨立階段安裝與驗證

FlexRIC 的角色是 near-RT RIC 與 xApp framework，不是 CUDA runtime，也不會自動讓 DQN 接到 E2。可先安裝並 smoke test，**主線無 RIC baseline 量測時保持停止**。

舊機確有 FlexRIC 目錄，但本專案尚未提供「乾淨重建、完整 E2/KPM/xApp 與 DQN 閉環已通過」的證據。

舊機來源與 build cache 的稽核資訊：

- FlexRIC SHA：`736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8`。
- compiler：`gcc-10`；`E2AP_VERSION=E2AP_V3`；`KPM_VERSION=KPM_V3_00`；`XAPP_DB=NONE_XAPP`。
- 這些是歷史環境紀錄，不保證該 SHA 可由任何 mirror 取得或與所有 srsRAN 版本互通。

Ubuntu 依賴起點：

```bash
sudo apt-get install -y \
  libsctp-dev cmake-curses-gui python3-dev pkg-config \
  libconfig-dev libconfig++-dev swig \
  autotools-dev automake bison libpcre2-dev
cmake --version
swig -version
```

先選定來源 revision，再依該版 README 核對 CMake／SWIG／compiler 要求。舊機 README 要求 SWIG≥4.1、CMake≥3.22 並提醒避開 GCC 11；Ubuntu apt 的 SWIG 可能較舊。必要時將 pinned SWIG 建在專案自己的工具目錄，指定 `SWIG_EXECUTABLE`，不用覆寫系統 SWIG。

[srsRAN 官方 E2 教學](https://docs.srsran.com/projects/project/en/latest/tutorials/source/near-rt-ric/source/index.html) 使用過 `br-flexric`／`1a3903a7` 與 GCC 10；它是參考組合，與舊機 SHA 不同。新機先選明確配對再建置，避免拿教學舊 revision 與任意新版混合。

建置範例流程（revision／compiler 先核對；不是無條件安裝指令）：

1. clone 官方來源 `https://gitlab.eurecom.fr/mosaic5g/flexric.git` 至 `third_party/flexric`，checkout 已記錄的 full SHA。
2. 如該 revision 要求 GCC 10，先確認 OS 套件可提供 `gcc-10 g++-10`。僅在此 build 用 `CMAKE_C_COMPILER`／`CMAKE_CXX_COMPILER` 指定，避免改全系統 compiler alternatives。
3. `cmake -S third_party/flexric -B third_party/flexric/build -DE2AP_VERSION=E2AP_V3 -DKPM_VERSION=KPM_V3_00 -DXAPP_DB=NONE_XAPP`，再加入所選 compiler／SWIG 的參數。
4. `cmake --build third_party/flexric/build -j2`；依版本執行測試。服務模型安裝／config 路徑依 pinned README 決定，記錄所有系統寫入；不因範例需要就預設裝 MySQL。
5. 先跑 framework 的 agent emulator + nearRT-RIC + monitoring xApp；通過後才接 srsRAN。
6. 核對 gNB YAML 的 E2 agent enable、RIC addr／port／bind、KPM metrics 開關與報告週期，保留 E2 Setup、subscription、indication logs／PCAP。以所選 binary 的 schema 為準，不照抄不同版欄位。
7. 有 subscription success 還不夠：需確認持續收到、內容可解碼且來源清楚的 KPM。dummy／零值不得當成實體 radio measurement。
8. 沒有有效 metric 或沒有支援的控制動作時，只完成監控整合，不宣稱 DQN 控制迴路或自動 CPU allocation 已完成。

正式 RIC 開銷比較需加入「無 RIC」「RIC+monitoring」「RIC+CUDA xApp」獨立對照，固定報告週期、xApp CPU mask 與資料庫設定。

## 6. RT、PMU 與主機資源前置驗收

先在一般 SSH 終端確認權限，必要時使用現有 sudo wrapper。agent sandbox 的 `NoNewPrivs=1`／零 capabilities 不能由 Python 自行解除；不要把 sandbox 失敗解讀成主機不支援。

- gNB 自行設 RT policy；Python runner 與 AI 維持 SCHED_OTHER。不要把整個 runner 用 `chrt` 設成 RT。
- 每秒驗證所有 DU threads 的 mask；main pool 實際三個且有 RT，RU 也需記錄。
- 檢查 sched_rt runtime/period；若考慮修改、CPU governor、IRQ placement，先記錄原值與新方案，在新批次前固定，保留恢復方式。不要直接永久關閉 RT throttling 當成預設修正。
- `perf_event_paranoid` 由 wrapper 記錄、暫設 1 並在收尾恢復；不要永久改成 -1。量測需排除同時執行的其他重型 profiler。

四項 PMU probe（需在具權限的主機終端執行）：

```bash
sudo perf stat -x ';' -e cache-references,cache-misses,instructions,cycles \
  -- python3 -c 'sum(range(1000000))'
```

不能只用 `sleep` 證明有 instructions／cycles。正式採集須 attach 到 DU threads，不是 AI。PMU `<not supported>`、`<not counted>`、coverage<90%、非法值／必要分母為零都視為不可用，不補零。

沒有可用 PMU 時，先停 PMU 主線並記錄失敗。若另做 proc-only，需明訂新 collector 協定、重新 baseline；現有 remote orchestrator 不會自動降級，也不能產生假 cache 圖。Nsight 的 GPU counters 與 perf 的 CPU counters 分開報告。

## 7. GPU 主機上的實驗階段與 gate

### P0：環境與功能 smoke

完成 inventory、相容性 lock、乾淨 srsRAN 建置、CUDA smoke、PMU probe、實際 worker／RT audit。FlexRIC 可另建，但暫不共置於 baseline。

新主機 CPU layout plan 要在第一批前記錄：DU main pool、RU、AI CPU workers、observer 的 CPUs，physical core／SMT／NUMA 對應，GPU NUMA affinity。若無足夠資源做所宣稱的實體隔離，縮小研究範圍並明示。

### P1：先取得新主機的 DU-only baseline

先固定一個場景（預設 UL-only，另標明與舊雙向不同），每種 planned layout 各十次：

- 30 秒暖機、60 秒採樣，time_scaling=1；沒有 decoder 工作仍是失敗。
- 十次全有效，完整逐秒 mask／RT 證據，沒有漏秒補採。
- 三項跨 run CV≤5%：每秒 enqueue_avg 的 run median、每秒 enqueue_max 的 run median、每秒 enqueue_max 的 run maximum。
- RT warning 上限 0；沿用唯一備援：兩組全有效且全部 CV 通過、僅 RT 不過，才可各完整重跑一次 RT≤1；其他情況停止。新 GPU automation 若採不同備援，必須在第一批前另訂協定，不能依結果改。
- 若無效 run 導致 CV 不計算，寫 unavailable，不宣稱所有 CV 已實測超標。

先固定所有會進 fingerprint 的程式、config 與套件，再跑此批。完成 baseline 後修改工作負載／採集程式、binary、layout、collector 等，需重新取得相符 baseline。

### P2：獨立 AI CPU／CUDA 校準

先測 AI-only，確認 loss 有限、更新數正確、CPU threads、GPU memory／utilization 與 end-to-end timing。小 DQN 可能被 Python／kernel launch 開銷主導，沒有加速也需保留。

目前模型為 16→256→256→4 MLP、batch=128、replay capacity=20000、Adam、合成狀態／reward；一個 step 是 **minibatch optimizer update**，不是環境互動次數。先維持此工作量；如擴大 batch／模型，再另建 workload ID，不能只有 GPU 版本偷偷放大。

### P3：同機 CPU／CUDA 共置比較

以下是預定設計；GPU runner 尚待實作，不能把舊 `remote_study.py` 跑完當成已完成 CUDA。

| 條件 | DU layout | AI device／CPU threads | 重複 |
|---|---|---|---:|
| S0 | shared、split | none | 各 5 |
| C1/C2/C4 | shared、split | CPU，1／2／4 intra-op threads | 各條件 5 |
| G1 | shared、split | CUDA，host intra-op=1、interop=1 | 各 5 |

共 10 條件 × 5 repeats = 50 attempts，另有兩組共 20 次前置 baseline。先依硬體核對可行性，第一批前鎖定；GPU 劑量擴充另列新矩陣，不能將 CPU threads=4 誤稱 GPU 四倍負載。

- 固定 seed 隨機／區組排序，依 repeat 配對；穿插 S0 controls，S0 無效或 RT 超過同批上限就停，未執行數明列。
- 主比較保留相同 model／batch／precision／訓練語義；先固定 FP32 與 TF32／AMP 設定。AMP、compile、CUDA graphs 另作後續優化軸。
- 同時報告「最大可達 AI throughput」與「匹配 AI updates/s 下的 DU 延遲」。後者需要實作有明確節拍的 rate limiter，不用 busy-wait 製造額外干擾。
- 每條件 planned=5；完整性至少三組相同 repeat 的有效配對。仍保留全部 invalid／not attempted，不能事後挑成功配對掩蓋失敗。
- 新 GPU 主機自身 CPU-only 是 GPU 比較的對照；舊 Xeon VM 只作背景，不能把換 CPU、換 host 的差異稱為 CUDA 效果。

### P4：FlexRIC／xApp 延伸

P1–P3 有可用證據後，或另開完全標記的功能整合批次，才加入 RIC。先 monitoring，之後才定義 state／action／reward 與控制可用性；不得假設 KPM 或 E2SM-RC 已支援動態 taskset／cgroup 操作。

若要讓 GPU xApp 真正控制 CPU 配額，需明訂執行端／權限／API、更新週期、rollback、action latency 與錯誤處理，並與靜態分配對照。不要在正式資料產生途中任意動態調整未記錄的 CPU masks。

## 8. 新機 Codex 要實作的程式項目

以下皆為 **TODO，現在不存在完整 CUDA 實作**：

1. **Topology/config 外部化**：現已有 CSV role plan；依新主機適配該配置，runner 與 audit 共用，報告記錄所用 plan。預先驗證 mask 非空、在 cpuset 內、所宣稱的 physical isolation 與實際 topology 相符。
2. **DQN device 參數**：新增明確 `--device cpu|cuda`，CUDA 不可用就 fail，不能默默 fallback CPU；維持 CPU 舊語義及明確 workload ID。
3. **記憶體／計算放置**：online／target、batch tensors、index tensors、optimizer state 裝置一致。分開記錄 replay 在 host 或 GPU；CPU replay+H2D 與 GPU-resident replay 是兩種實驗策略，不混算。
4. **同步與計數**：現有程式 `float(loss.detach())`、`int(argmax)` 若直接搬到 GPU 會引入同步。先定義 end-to-end step，包含必要環境互動與 transfer；校準用 CUDA events／同步量到完成時間，正式計數在明確邊界確認完成。不可把排入 CUDA queue 的數量當完成 updates/s，也不可先排隊再在末尾倒灌到前幾秒。
5. **計時效應**：每 step 同步是可重現但會改變執行特性的一種方案；批次同步／events 需同樣定義。量測方案先校準並固定，記錄端到端 wall／monotonic 與 GPU event 時間，GPU kernel time 不能取代整個 AI 工作時間。[PyTorch CUDA 語義](https://docs.pytorch.org/docs/2.15/notes/cuda.html)
6. **ready 與 warmup**：CUDA context、allocator、首輪 kernel／optimizer state 完成初始化與 warmup 後才 ready，再進共同條件暖機。固定初始化流程；不能只對 GPU 多暖機後隱藏於報告。
7. **GPU telemetry**：在固定採樣頻率記錄 GPU UUID、utilization、memory、temperature、power／clocks（可用欄位）；記錄 GPU 上其他程序。欄位不支援標 NA，GPU utilization 不等於有效工作量。
8. **metadata／schema**：run CSV 增加 device、workload ID、CPU threads、GPU ID、precision、transfer/replay policy；DQN thread audit 仍為 SCHED_OTHER。圖表區分 CPU／CUDA，不再只以 thread 數代表 AI 強度。
9. **版本與 gate**：context/fingerprint 納入拓撲、環境 lock、GPU driver／UUID、AI schema、程式與模型配置。比較軸（device）放在每個 condition，整個矩陣共用固定 plan；不能因切 condition 而錯誤套用不同 baseline，也不能忽略環境改動。
10. **新 automation**：新增或擴充 GPU 專用 orchestrator，plan 先落盤、single-run lock、tmux、停止清理、sysctl 恢復、PMU/GPU 失敗原因保留，避免與舊 CPU session 同時跑。
11. **必要回歸測試**：device mismatch、CUDA unavailable、completed-step counting、零／漏吞吐秒、漏採／clock jumps、mask/worker 不符、S0 gate 阻擋、無效比例與配對不混批。硬體 CUDA 測試無 GPU 時要明確 skip，不能標 GPU PASS。

## 9. 分析與交付要求

每個 run 保存原始 gNB log、config、DU thread snapshots、perf CSV、AI throughput、GPU telemetry、開始／結束時間、returncodes、失敗原因與環境 fingerprint。

至少輸出：

1. 每條件有效／無效／未執行與分母，baseline CV／RT gate 與停止原因。
2. DU executor interval 分布、逐秒 RT 訊息，所有有效 run 原始點。
3. DU latency vs AI completed updates/s／inference/s 的 CPU／CUDA 圖。
4. 相同 repeat 的 shared／split 配對差值與樣本數；報告變異／不確定性，不僅均值。
5. DU CPU IPC、generic cache miss rate／MPKI；另列 GPU telemetry，不能由 cache miss 變化直接斷言 cache 因果瓶頸。
6. 限制：單機合成負載、host／VM 差異、沒有逐任務 P99、沒有真實 UE throughput、DQN 不是已部署的 RAN 控制器。

報告與 code／aggregate CSV／圖進 Git；binary、venv、build、raw logs 與大型 ZIP 使用另行保存方式。不要把 token、私鑰或機器帳密寫進交接文件。

## 10. 接手順序與完成清單

新機 Codex 收到「請依本檔開始」後，按順序執行：

- [ ] 確認 checkout／補齊未提交交接檔；核對是否已有實驗在跑。
- [ ] 更新舊 UL-only 批次最終狀態；沒有原始證據就明示。
- [ ] 產出新主機 inventory 與 software compatibility／lock。
- [ ] 安裝缺少的 OS 依賴與可用 driver；驗證 CUDA smoke。
- [ ] pinned srsRAN 乾淨建置、worker patch、YAML dry-run、單元測試。
- [ ] 外部化實際 topology plan；驗證 PMU、三 workers、RT、每秒採集。
- [ ] 在正式 baseline 前完成並驗證 CUDA runner／schema，凍結版本。
- [ ] 新主機兩種 layout 的十次 baseline；未過就診斷，不進共置矩陣。
- [ ] baseline 通過後跑同機 CPU／CUDA 矩陣、配對分析與失敗比例。
- [ ] FlexRIC emulator／E2／KPM monitoring 功能驗證；RIC 共置獨立批次。
- [ ] 最後才規畫具可驗證 action 的 CUDA xApp／控制閉環。

每次停下或交接時更新 `docs/gpu-migration-status.md`：目前階段、完成證據、正在跑的 session／results 路徑、下一個命令、需要一般 SSH 權限的步驟與已知阻礙。用中文簡潔回報；不要將「已安裝」「dry-run 通過」「採樣有效」「baseline PASS」「矩陣完成」混為一談。

## 11. 使用者交給新機 Codex 的提示詞

> 請先讀 GPU_HANDOFF_PLAN.md、README.md 與適用的 AGENTS.md，接手 AI–RAN CPU/CUDA 共置實驗。先檢查目前 checkout、盤點硬體與缺少套件，更新 docs/gpu-migration-status.md，依計畫完成環境與功能驗證、實作 CUDA runner，再凍結版本重跑新主機 baseline。保留失敗證據；baseline 不過不能進正式 AI 矩陣。FlexRIC 按獨立階段驗證。需要 sudo、driver 安裝或重開機時說明具體步驟；可在現有權限內完成的工作持續執行。

## 12. 官方資料與版本核對入口

以下資料於 2026-11-07 查閱，實際安裝時仍需核對 pinned revision／硬體：

- [srsRAN Project 安裝](https://docs.srsran.com/projects/project/en/latest/user_manuals/source/installation.html)
- [srsRAN O-RAN NearRT-RIC／FlexRIC 教學](https://docs.srsran.com/projects/project/en/latest/tutorials/source/near-rt-ric/source/index.html)
- [FlexRIC 官方來源](https://gitlab.eurecom.fr/mosaic5g/flexric)
- [Ubuntu NVIDIA driver](https://ubuntu.com/server/docs/how-to/graphics/install-nvidia-drivers/)
- [NVIDIA CUDA Linux 安裝](https://docs.nvidia.com/cuda/cuda-installation-guide-linux/)
- [PyTorch 安裝選擇器](https://pytorch.org/get-started/locally/)
- [PyTorch 舊版本安裝](https://pytorch.org/get-started/previous-versions/)
- [PyTorch CUDA semantics](https://docs.pytorch.org/docs/2.15/notes/cuda.html)
