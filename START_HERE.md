# Source package：新硬體從這裡開始

本包只提供專案程式、設定、測試、Markdown 報告，以及本機 srsRAN/FlexRIC 來源快照。不含實驗 raw data、彙整 CSV、圖表、binary、build、Git metadata 或虛擬環境。`configs/*.csv` 是 CPU 角色配置，不是量測數據；upstream 的原有測試 fixtures 屬來源的一部分。

請先讀：

1. [新主機第一天檢查](docs/new-host-day1.md)
1. [Baseline v4 協定（新機用這版）](docs/baseline-v4.md)
1. [最新實驗摘要](docs/hardware-handoff-20261108.md)
2. [README](README.md)
3. [GPU／CPU 主機安裝與研究交接](GPU_HANDOFF_PLAN.md)
4. [來源與打包紀錄](SOURCE_PROVENANCE.md)

舊報告原本連到圖／CSV／raw logs 的連結在這個 source-only 包中不可用；數字摘要已保留在 Markdown。

## 附帶來源與重新建置

`third_party/srsRAN_Project` 是舊機已知 upstream revision 的工作樹快照，包含既有 E2/KPM 變更，並已在封裝時套用明訂 worker 數修正。不是純 upstream release；patch 與 revision 在 provenance 文件。`third_party/flexric` 是舊機已知來源快照，尚未證明與新硬體/OS 完整互通。

先按 GPU_HANDOFF_PLAN.md 安裝與 OS 相符的 compiler、CMake、FFTW、mbedTLS、SCTP、yaml-cpp、gtest、Python venv、perf 等依賴。系統套件與 CUDA wheel 不在本包中，安裝仍需要套件來源／網路。CUDA 可稍後再裝；先驗證 DU CPU baseline。

以下假設終端位於解壓後的 `ai-ran-performance` 根目錄：

```bash
mkdir -p bin
cmake -S third_party/srsRAN_Project -B third_party/srsRAN_Project/build \
  -DCMAKE_BUILD_TYPE=Release
cmake --build third_party/srsRAN_Project/build --target gnb -j2
cp third_party/srsRAN_Project/build/apps/gnb/gnb bin/gnb
bin/gnb --version
sha256sum bin/gnb
python3 -m venv .venv-study
.venv-study/bin/python -m pip install -r requirements-study.txt
.venv-study/bin/python -m unittest discover -s tests -v
```

本包的 srsRAN source **已套 worker patch，不再執行 GPU_HANDOFF_PLAN.md 裡的 git clone／git apply 步驟**。其他安裝／相容性檢查仍適用。這是待在新機驗證的重建流程，沒有預先宣稱新 OS 可無條件建置成功。

source 無 `.git`，部分 upstream 的 version metadata 可能無法自動取得；保留 SOURCE_PROVENANCE.md 的 revision 與 patch 紀錄，不因 build 顯示 unknown 而丟失來源身分。不要直接呼叫舊機專用 `scripts/build_worker_fix.py`。

FlexRIC 先獨立建置及 emulator smoke，主線 baseline 不啟動 RIC；版本／compiler／SWIG／E2AP/KPM 互通檢查依 GPU_HANDOFF_PLAN.md。

## 跑正式 baseline 前

新機使用 v4：`configs/cpu-layout-v4.csv`（DU 兩組相同，只改 AI 位置；RU 不在 CPU 0；保留 gNB 空閒核心）。v3 只保留作為歷史紀錄。先執行 `python3 scripts/check_env.py` 和 `scripts/make_layout.py`，依照實際拓撲產生 v4 配置（`configs/cpu-layout-v4.csv` 是舊 VM 的配置）。原 CSV 是舊 VM 的 logical CPU 設定；如果新機不能提供該配置，先適配並記錄新協定，不直接執行。

確定 topology、PMU、RT 權限、binary 與配置後，在一般終端啟動：

```bash
python3 scripts/make_layout.py   # 產生 configs/cpu-layout-v4-$(hostname).csv
sudo LAYOUT_PLAN=configs/cpu-layout-v4-$(hostname).csv bash scripts/start_baseline_v4.sh
```

查詢進度：

```bash
python3 scripts/study_status.py
```

不以反覆重跑挑成功樣本，不放寬 CV／RT gate。v4 唯一事前宣告的差異：max-of-max 只報告不當 gate；未進入 active PHY 的啟動失敗最多替換 3 次（見 docs/baseline-v4.md）。不要同時跑兩批研究。CUDA 支援尚待實作，安裝 CUDA 不會自動產生 CUDA 共置實驗。

## 給這台機器 Codex 的指令

> 請完整讀取 START_HERE.md、docs/hardware-handoff-20261108.md 與 GPU_HANDOFF_PLAN.md，盤點實際硬體、依賴與權限。使用包內已套 worker patch 的 srsRAN 來源重新建置，適配 CSV CPU roles 並跑驗證；先取得本機 DU-only baseline，再依計畫處理 CPU/CUDA AI 與 FlexRIC。記錄環境、失敗原因與 provenance，不沿用舊 VM baseline。缺少權限時提供一般終端具體操作；能在現有權限完成的工作先完成。
