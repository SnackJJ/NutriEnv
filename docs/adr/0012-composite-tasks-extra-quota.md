# Composite tasks score multiple oracles and occupy extra quota

v1.0 起允许复合题：一个 Task 的 query 要求多步（如先 log 再 recommend），携带
**多个子 Oracle**，判分要求每个子 Oracle 的 end state 都匹配（Pass ⇔ 全部
`end state == 对应 sub-oracle`，判分铁律语义不变）。复合题**额外占用配额**，
在基础 240 题之外另加，不挤占单 family 配额。

理由：真实用户一句 query 可能同时要求记录和推荐（"我中午吃了 X，晚上该吃什么？"），
当前"一题一个 family、一个 Oracle"的形状装不下。备选：不引入复合题（否决——丢失
真实场景）、复合题算进某 family 配额（否决——配额账目混乱）、独立复合配额 + 多
Oracle（采纳）。Task 的 primary Family 仍只有一个（分类账不变），sub-oracles 是
额外合同。复合题形状与配额数字在 v1.0 冻结前单独设计并再裁决一次。
