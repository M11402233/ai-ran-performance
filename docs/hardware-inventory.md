# 本次環境盤點

測試日期：2026-10-30 UTC。原始資料：`results/raw/inventory.json`、`environment-probe.json`。

| 項目 | 實測 |
|---|---|
| OS | Ubuntu 22.04.5 LTS，kernel 5.15.0-198-generic |
| 虛擬化 | KVM full virtualization |
| Guest CPU | Intel Xeon Silver 4110 @ 2.10 GHz，8 個 online vCPU，允許 CPU 0–7 |
| Guest 拓樸 | 1 socket × 8 cores × 1 thread；僅 guest 視角，無法證明 host 獨占核心或 SMT 狀態 |
| 指令集 | AVX2、AVX-512 flags 可見 |
| RAM | 約 15 GiB（16 GB 級），初始 available 約 14 GiB；swap 4 GiB |
| 儲存 | 同一 79 GiB 分割區，初始約 28 GiB available；不推定為 SSD |
| GPU | 此工作階段未看到 NVIDIA／DRI 裝置，沒有 nvidia-smi；無法執行 CUDA 實驗 |
| 建置相依 | cmake/gcc/g++、FFTW、mbedTLS、SCTP、yaml-cpp 已存在 |
| Python | numpy、pandas、matplotlib 可匯入；無 PyTorch |
| profiler | 未找到 perf 執行檔；直接 perf_event_open(cycles/cpu-clock) 均 EACCES |
| 權限 | 無 effective capabilities；Seccomp=2；perf_event_paranoid=4；cgroup v2 為唯讀 mount |
| RT | gNB 提升 thread scheduling priority 失敗；仍可啟動 |
| 頻率／溫度 | 本工作階段無 cpu0 cpufreq 介面，thermal 僅 cooling devices，不能確認實體頻率／熱節流 |

目前工作階段的 DNS 解析失敗、loopback UDP 操作受限；這些是此 context 的觀察，不能證明 VM 一般終端或 host 的權限也相同。以一般終端重新執行 `python3 scripts/probe.py` 可比較。

srsRAN 原有原始碼位於 `/home/cindy2/oran-lab/srsRAN_Project`。HEAD：`d2f4b70dda8e2c557d5b05a0ac5f92dbddda19bc`；binary 自報 25.10.0。原樹有 E2 KPM 的未提交修改，已保留 patch，未修改原樹。現有 binary 的完整建置來源不能只靠 HEAD 證明；SHA256 見 inventory.json。正式研究應另用乾淨且固定版本重建。
