#!/usr/bin/env bash
# Cheap VM/kernel vs. design diagnosis. Does not change sysctl, IRQ affinity or the study.
#   sudo bash scripts/diagnose_host.sh kernel [SINCE]   # scan kernel log, default since 2026-10-30
#   sudo bash scripts/diagnose_host.sh live [SECONDS]   # while a baseline runs: per-thread CPU%, per-CPU irq/steal
set -euo pipefail
cd "$(dirname "$0")/.."
out=results/diagnostics/$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "$out"
case "${1:-}" in
  kernel)
    since=${2:-2026-10-30}
    journalctl -k --since "$since" --no-pager > "$out/kernel.log" || true
    grep -iE 'rt throttling|rcu.*stall|soft lockup|hung_task|clocksource|watchdog' "$out/kernel.log" \
      > "$out/kernel-matches.log" || true
    echo "Matches: $(wc -l < "$out/kernel-matches.log") lines -> $out/kernel-matches.log"
    echo '  "RT throttling activated"  -> RT threads saturating CPUs (likely busy-polling): design side'
    echo '  "rcu ... stall"/"soft lockup" -> kernel work starved by RT threads, or the VM was paused'
    echo '  "clocksource ... unstable"   -> host-side scheduling/pausing of the guest'
    echo '  NOTE: "RT throttling activated" is printed once per boot; later throttling is silent.'
    # Per-CPU counters show whether throttling is still happening (needs root/debugfs).
    for f in /sys/kernel/debug/sched/debug /proc/sched_debug; do
      if [[ -r $f ]]; then grep -E '^cpu#|rt_throttled|rt_time' "$f" > "$out/rt-throttle-counters.txt"; break; fi
    done
    ;;
  live)
    seconds=${2:-90}
    pid=$(pgrep -f 'bin/gnb' | head -n1) || { echo 'gNB is not running; start one baseline first.' >&2; exit 1; }
    command -v pidstat >/dev/null || { echo 'Install sysstat (pidstat/mpstat) first.' >&2; exit 1; }
    pidstat -t -p "$pid" 1 "$seconds" > "$out/pidstat-threads.txt" &
    mpstat -P ALL 1 "$seconds" > "$out/mpstat.txt" &
    cat /proc/interrupts > "$out/interrupts-before.txt"
    wait
    cat /proc/interrupts > "$out/interrupts-after.txt"
    echo "Saved to $out"
    echo '  RU/main_pool thread near 100% in pidstat -> busy-polling; check %irq and %steal per CPU in mpstat.'
    ;;
  *)
    sed -n 2,4p "$0"; exit 2 ;;
esac
