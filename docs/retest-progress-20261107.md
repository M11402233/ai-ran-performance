# 修正版重測進度快照

時間：2026-11-07T14:54:43.106910+00:00

```text
Session: remote-session-20261107T145206Z status: primary-baselines
baseline shared: completed=2/10
  00-shared-DQN0-0 valid= False reason= No active decoder within 30 seconds; affinity not verified for all sampled threads; no verified FIFO/RR DU worker; sample window missing RT max/s= 0
  01-shared-DQN0-1 valid= True reason=  RT max/s= 60
   PMU: {'cache-references': 2027437888.0, 'cache-misses': 384519974.0, 'instructions': 161694064592.0, 'cycles': 165524600335.0} miss%= 18.966 IPC= 0.977
   main_pool counts: [3]
  02-shared-DQN0-2 in progress; counters not finalized
```

這是進度快照，非最終驗收。第一筆啟動後 decoder 無活動，第二筆有完整有效採樣但 RT max/s=60（預定上限 0），因此本批無法通過既定 gate。讓原排程完成並保留兩配置紀錄，不重複啟動、不修改工作量或門檻。

第二筆實測四項 PMU coverage 均為 100%，無 not supported/not counted。main-pool 三 workers 均為 FIFO 96，RU 為 FIFO 98。

後續：先完成當前兩批診斷，檢查 split 是否維持三 workers、兩組無效比例與延遲 CV。未通過則不執行 DQN；可另開預先定義的 UL-only 場景，重新測兩組 baseline。UL-only 與原雙向場景不可合併計算。

查詢：`python3 scripts/study_status.py`。正式完成報告由既有 orchestrator 收尾產出。
