---
name: livingmemory-helper
description: "春雪记忆系统完整工具指南。当需要回忆、搜索、管理记忆时使用。22个工具覆盖记忆全生命周期。"
---

# 春雪记忆系统 — 工具决策树 v1.0

> 你有 **22 个工具**，不是只有 recall + memorize。
> 选对工具 = 省时间 + 省 token + 更懂橘子。

## 一、快速决策表（看到什么 → 用什么）

| 橘子说的话 / 你需要做的事 | 用哪个工具 | 为什么 |
|---|---|---|
| "你还记得XXX吗？" / "我们之前聊过什么" | `haruyuki_recall_memory` | 精准召回特定记忆 |
| "今天聊了什么" / "今天发生了什么" | `haruyuki_today_summary` | 当日时间线概览 |
| "关于XXX我们聊过几次" / "最近XXX话题" | `haruyuki_search_memory` | 跨天广泛搜索 |
| "最近我们过得开心吗" / "最近状态" | `haruyuki_sentiment_trend` | 情感趋势分析 |
| "帮我记住这个" / 重要信息出现 | `recall_long_term_memory`(memorize) | 持久化到长期记忆 |
| "你了解我什么" / "你觉得我是什么样的人" | `haruyuki_profile` | 记忆画像特征 |
| "你有什么预言" / "我的规律" | `haruyuki_prophecy` | 预测与验证 |
| "你现在的风格" / "你怎么说话的" | `haruyuki_expression` | 表达风格快照 |
| "这件事从哪来的" / "为什么会想起" | `haruyuki_causal_chain` | 因果证据链 |
| "这条记忆从哪来的" / 溯源 | `haruyuki_memory_trace` | L3→L2→L1 引用链 |
| "我有没有说过矛盾的话" / "记忆一致吗" | `haruyuki_conflict_check` | 矛盾检测 |
| "帮我设个提醒" / "有什么提醒" | `haruyuki_reminder` | 提醒系统 |
| "记住这个人/项目" / 实体管理 | `haruyuki_ontology_create` | 知识图谱 |
| "告诉我关于XX的信息" / 实体查询 | `haruyuki_ontology_query` | 实体详情 |
| "把XX和XX关联" | `haruyuki_ontology_link` | 关系建立 |
| "列出所有任务/人" | `haruyuki_ontology_search` | 实体搜索 |
| "XX有哪些相关的" / "谁负责" | `haruyuki_ontology_related` | 关系遍历 |
| "知识图谱多少数据" | `haruyuki_ontology_stats` | 统计概览 |
| "整理记忆" / "清理旧记忆" / "沉睡记忆" | `haruyuki_archive` | 归档管理 |
| "学到了什么" / 经验总结 | `haruyuki_knowledge` (list) | 知识库浏览 |
| 发现可复用经验 | `haruyuki_knowledge` (propose) | 提议毕业 |
| "家庭例会" / "今天全家干了啥" / "日报" | `haruyuki_family_meeting` | 家庭日报 |
| "家庭反馈" / "家人互动" / "最近谁给谁说了什么" | `haruyuki_family_status` | 反馈回路 |
| 记忆到复习时间了 | `haruyuki_reinforce_memory` | 间隔重复 |

## 二、工具生态全景（按功能分层）

### 第一层：记忆核心引擎
```
                    ┌──────────────────┐
   橘子说话 ───────►│ recall_memory    │ 精准召回（语义搜索）
                    └──────────────────┘
                    ┌──────────────────┐
                    │ today_summary    │ 当日概览
                    └──────────────────┘
                    ┌──────────────────┐
                    │ search_memory    │ 跨天搜索（广泛）
                    └──────────────────┘
```
**记住**：recall ≠ search。recall 是精准找某条记忆，search 是广泛找某个话题。

### 第二层：记忆深度分析
```
sentiment_trend  ─── 情感走势（开心/难过趋势）
profile          ─── 记忆画像（橘子的稳定特征）
prophecy         ─── 预言（基于规律预测未来）
expression       ─── 表达风格（亲密/温暖/俏皮度）
causal_chain     ─── 因果链（这件事的前因后果）
memory_trace     ─── 溯源链（这条记忆的信息来源链）
conflict_check   ─── 冲突检测（记忆矛盾）
```

### 第三层：记忆管理
```
reminder           ─── 提醒（创建/查看/取消）
archive            ─── 归档（沉睡记忆清理）
reinforce_memory   ─── 复习（间隔重复）
knowledge          ─── 知识毕业（经验→永久知识）
```

### 第四层：知识图谱
```
ontology_create  ─── 创建实体
ontology_query   ─── 查询实体
ontology_link    ─── 关联实体
ontology_search  ─── 搜索实体
ontology_related ─── 关系遍历
ontology_stats   ─── 统计
```

### 第五层：家庭协作
```
family_status   ─── 家庭反馈回路总览
family_meeting  ─── 家庭例会日报
```

## 三、常见误区（必读！）

### 误区 1：什么都用 recall_memory
```
❌ 橘子："你觉得我是什么样的人？" → recall_memory("橘子性格")
✅ 橘子："你觉得我是什么样的人？" → haruyuki_profile
```
recall 是搜原始记忆条目，profile 是从记忆中提炼的稳定特征画像。

### 误区 2：recall 和 search 不分
```
❌ 橘子："最近我们聊英语聊过几次？" → recall_memory("英语")
✅ 橘子："最近我们聊英语聊过几次？" → haruyuki_search_memory("英语", days=30)
```
recall 适合找某条具体记忆，search 适合找某个话题的所有相关记忆。

### 误区 3：不知道有知识图谱
```
❌ 橘子："橘子认识哪些人？" → recall_memory("认识的人")
✅ 橘子："橘子认识哪些人？" → haruyuki_ontology_search("Person")
```
知识图谱是结构化数据，比翻记忆条目快且准确。

### 误区 4：不用因果链
```
❌ 橘子："这件事后来怎么样了？" → recall_memory("这件事后来")
✅ 橘子："这件事后来怎么样了？" → haruyuki_causal_chain("这件事", direction="effect")
```
因果链追踪事件的来龙去脉，比关键词搜索精确得多。

### 误区 5：不用预言
```
❌ 你想提醒橘子某个规律 → 随口说
✅ 你想提醒橘子某个规律 → haruyuki_prophecy (先看有没有已验证的预言)
```

## 四、组合拳（多工具协同）

### 场景 A：橘子问"你还记得上次吵架的事吗？"
```
1. recall_memory("吵架")         → 召回相关记忆
2. causal_chain("吵架", "both")  → 追溯前因后果
3. conflict_check()              → 看有没有矛盾的记录
```

### 场景 B：橘子说"你觉得我们最近怎么样？"
```
1. sentiment_trend(days=14)      → 情感走势
2. today_summary()               → 今天发生了什么
3. profile()                     → 你们关系的稳定特征
```

### 场景 C：发现了一个重要的经验教训
```
1. haruyuki_knowledge(propose)   → 提议毕业
2. (等橘子确认后) haruyuki_knowledge(confirm) → 正式毕业
3. recall_long_term_memory(memorize) → 同时存入长期记忆
```

### 场景 D：记忆系统定期维护
```
1. archive(scan)                 → 扫描沉睡记忆
2. archive(list)                 → 查看候选
3. reinforce_memory(list)        → 查看到期复习
4. conflict_check()              → 检查矛盾
```

## 五、工具使用铁律

1. **先选对工具再调** — 不要什么都用 recall，每个工具有专门的用途
2. **能用组合拳就别单打** — 复杂问题用 2-3 个工具协同
3. **不跳过情绪先处理事** — 橘子问问题时先共情，再用工具查
4. **搜索 vs 回忆** — 精准找用 recall，广泛找用 search
5. **结构化 vs 时间线** — 人物/项目/关系用 ontology，事件/对话用 recall
6. **分析 vs 原始** — 要洞察用 profile/prophecy/sentiment，要原始记录用 recall/search

## 六、参考：TencentDB Agent Memory 对标

### v6.2 已实现 ✅

| 概念 | TencentDB 实现 | 我们的实现 | 文件 |
|------|---------------|-----------|------|
| **RRF 融合检索** | FTS5 + 向量 → RRF k=60 融合 | FTS5 + LIKE + 标签 → RRF k=60 融合 | `core/rrf_engine.py` |
| **上下文卸载** | L1 摘要 + L2 拓扑 + L3 三层压缩 | 三层压缩级联（Mild/Aggressive/Emergency） | `core/rrf_engine.py` |
| **过采样策略** | limit×3 过采样后过滤 | limit×3 过采样 + RRF 排序 | `core/rrf_engine.py` |

### v6.2 借鉴的核心理念

1. **多路并行检索** — 不同检索方法有不同优势（FTS5 精确 / LIKE 中文子串 / 标签语义），并行执行后融合比单路更强
2. **RRF 替代归一化** — 不同检索方法的分数尺度不同，RRF 只用排名（rank）避免了归一化问题
3. **分级压缩** — 不是一次性截断，而是按 token 占比分级处理（温和替换 → 激进删除 → 紧急截断）
4. **优雅降级** — 单路检索失败不影响其他路，RRF 无结果时降级到单路 search_memories

我们独有的（TencentDB 没有的）：
- **因果链** (causal_chain) — 事件来龙去脉追溯
- **预言** (prophecy) — 基于规律预测未来，到期自动验证
- **冲突检测** (conflict_check) — 记忆矛盾自动发现
- **表达风格联动** (expression) — 记忆画像驱动说话方式
- **家庭协作** (family) — 21 个模块互相反馈
