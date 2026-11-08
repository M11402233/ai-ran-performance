# 新 GPU 主機：第一天環境檢查

目標：判斷這台機器是否適合做 DU／AI 共置實驗，並產生它的 v4 CPU 配置。這一天不做正式量測。

## 1. 基本資訊（不需要 sudo）

```bash
cd ~/ai-ran-performance
python3 scripts/check_env.py                  # 檢查結果存到 results/env/<host>-<time>.json
lscpu
lscpu -e=CPU,CORE,SOCKET,NODE,ONLINE          # 實體核心、SMT、NUMA
cat /sys/devices/system/cpu/smt/control       # on / off / notsupported
numactl -H 2>/dev/null || ls /sys/devices/system/node
nvidia-smi
nvidia-smi topo -m                            # GPU 接在哪個 NUMA node、靠近哪些 CPU
systemd-detect-virt                           # none 才是裸機
uname -r; cat /proc/cmdline
free -h; df -h ~
```

## 2. 需要權限的檢查

```bash
sudo apt install -y rt-tests sysstat linux-tools-$(uname -r) numactl
sudo python3 scripts/check_env.py --rt-seconds 60    # 加上 SCHED_FIFO、PMU、cyclictest
# 單獨做 RT 延遲測試（會壓住候選的 DU CPU 60 秒）：
sudo cyclictest -m -q -p95 -i200 -D60 -a 1-5 -t5
```

## 3. 判斷是否適合

| 項目 | 適合 | 需要處理 |
|---|---|---|
| 虛擬化 | `none`（裸機） | VM：要求專用、不超額配置的綁核 pCPU |
| 實體核心（同一個 NUMA node） | ≥ 10 | 8 剛好夠；< 8 就要先改協定 |
| SMT | off，或 sibling 不被使用 | 在 BIOS 或 `smt/control` 關閉 |
| CPU governor | `performance` | `sudo cpupower frequency-set -g performance` |
| cyclictest 最差延遲 | < 50 µs | 50–200 µs 要先調整 host；≥ 200 µs 不適合 |
| 背景負載 | 每顆 CPU < 5% | 先停掉其他服務或工作 |
| PMU | cycles／instructions／cache 都能計數 | 只能用 `--collector proc`，不能下 cache／IPC 結論 |
| GPU | `nvidia-smi` 正常、有 driver CUDA 版本 | 先裝好 driver |
| 依賴 | `check_env.py` 沒有 FAIL | 安裝缺少的 -dev 套件 |

## 4. 產生這台主機的 v4 配置

```bash
python3 scripts/make_layout.py               # 預設用 GPU 所在的 NUMA node
cat configs/cpu-layout-v4-$(hostname).csv
```

這個配置的原則：每個實體核心只用一個 logical CPU；housekeeping 和 observer 放在第一個核心（≥ 10 核時放兩個）；RU、3 個 worker、1 個空閒核心組成 DU；split 的 AI 另外用 2 顆核心。DU 和 AI 的 SMT sibling 不分配任何角色。舊 VM 的 `configs/cpu-layout-v4.csv` 不會被覆蓋。

## 5. 建置與 smoke test（依照 START_HERE.md）

```bash
cmake -S third_party/srsRAN_Project -B third_party/srsRAN_Project/build -DCMAKE_BUILD_TYPE=Release
cmake --build third_party/srsRAN_Project/build --target gnb -j$(nproc)
mkdir -p bin && cp third_party/srsRAN_Project/build/apps/gnb/gnb bin/gnb
python3 -m venv .venv-study && .venv-study/bin/python -m pip install -r requirements-study.txt
.venv-study/bin/python -m unittest discover -s tests
```

## 6. 診斷用 split（2–3 次，不算 baseline）

```bash
sudo .venv-study/bin/python scripts/run_study.py baseline --layout split --collector proc \
  --config configs/du-uplink-only.yml --layout-plan configs/cpu-layout-v4-$(hostname).csv
# 第 3 或第 4 個 attempt 開始時按 Ctrl-C
python3 analysis/cpu_time_diag.py results/raw/baseline-split-<time>
```

和舊 VM 的結果對照：每秒 enqueue_avg 中位數約 85 µs，但 3 次中有 2 次出現 750 行以上的 RT 警告。如果新機沒有 RT burst，再凍結配置，執行 `sudo LAYOUT_PLAN=configs/cpu-layout-v4-$(hostname).csv bash scripts/start_baseline_v4.sh`。
