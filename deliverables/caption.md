# 圖說：觀察與限制

A：每次 S0 的每秒平均延遲中位數，分批標示 gate 與 RT 上限，不把原批與備援混合。
B：所有已採樣 run 的每秒 RT 訊息分布，包含無效 run；不是唯一 missed-slot 數。
C：每個有效矩陣 run 的 DU 延遲與 DQN optimizer updates/s；沒有矩陣就明示未量到。
D：相同 DQN threads／repeat 的 split 相對 shared 延遲變化，標 n；負數表示觀測延遲較低，不代表已證明分核的因果效應。
E：每批有效、無效、未執行的絕對數；詳細 invalid/attempted 比例在 quality-summary.csv。
F：驗收狀態、量測範圍與限制。圖中的每秒指標不是逐任務分布；不宣稱 P99 或 cache root cause。

本圖對應遠端狀態：stopped；量測完成前的圖是進度快照，不是最終結論。
