# -*- coding: utf-8 -*-
"""
召回质量基准测试 v1.0 — 借鉴 TencentDB PersonaMem 评测思路的本地化版本
用法: python scripts/recall_benchmark.py [样本数，默认60]
原理: 从 livingmemory.db 分层抽样记忆 -> 生成伪查询 -> 四策略检索 -> Hit@k / MRR / 延迟
铁律: 全程只读连接，零写副作用（不污染 access_count / atoms 强化）
"""
import sqlite3, re, json, time, random, statistics, sys, os
from datetime import datetime

DB = os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugin_data",
                  "astrbot_plugin_livingmemory", "livingmemory.db")
DB = os.path.abspath(DB)
SAMPLE_N = int(sys.argv[1]) if len(sys.argv) > 1 else 60
random.seed(42)  # 可复现

# ── 连接（只读） ──
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

TIER_W = {0: 1000, 1: 100, 2: 10, 3: 1}

def fts_search(conn, query, limit):
    """FTS5 路 v6.5.2: lmem_fts_t3 (trigram)——子串语义，查询需>=3字"""
    if len(query) < 3:
        return []
    try:
        safe_q = '"' + query.replace('"', '""') + '"'
        rows = conn.execute(
            "SELECT d.id FROM documents d INNER JOIN lmem_fts_t3 f ON f.rowid = d.rowid "
            "WHERE lmem_fts_t3 MATCH ? ORDER BY rank LIMIT ?", (safe_q, limit)).fetchall()
        return [r["id"] for r in rows]
    except Exception:
        return []

def like_search(conn, query, limit):
    rows = conn.execute(
        "SELECT id FROM documents WHERE text LIKE ? ORDER BY created_at DESC LIMIT ?",
        (f"%{query}%", limit)).fetchall()
    return [r["id"] for r in rows]

def rrf_merge(lists, k=60, limit=30):
    """RRF: score = sum(1/(k+rank+))，内联自 helper/core/rrf_engine.py"""
    scores = {}
    for lst in lists:
        for rank, item_id in enumerate(lst):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (k + rank + 1)
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return [i for i, _ in ranked[:limit]]

def tier_sort(ids_with_score, docs):
    """线上真实路径：Tier 权重二次排序（L0=1000 ... L3=1）"""
    return sorted(ids_with_score, key=lambda i: (
        TIER_W.get(docs.get(i, {}).get("tier", 3), 0), ids_with_score[i] if isinstance(i, int) else 0
    ), reverse=True) if False else sorted(
        [i for i in ids_with_score], key=lambda i: (TIER_W.get(docs.get(i, {}).get("tier", 3), 0), ids_with_score[i]),
        reverse=True)

# ── 1. 分层抽样 ──
tiers = con.execute(
    "SELECT memory_tier as tier, COUNT(*) c FROM documents GROUP BY memory_tier").fetchall()
total = sum(t['c'] for t in tiers)
per_tier = max(4, SAMPLE_N // max(len(tiers), 1))
docs = {}
for t in tiers:
    rows = con.execute(
        "SELECT id, text, memory_tier as tier FROM documents WHERE memory_tier=? "
        "AND length(text)>=20 ORDER BY RANDOM() LIMIT ?", (t['tier'], per_tier)).fetchall()
    for r in rows:
        docs[r["id"]] = {"text": r["text"], "tier": r["tier"]}

# ── 2. 伪查询生成：抽 1-2 个连续中文段（>=2字） ──
CN = re.compile(r"[\u4e00-\u9fff]{2,8}")
def make_query(text):
    segs = [s for s in CN.findall(text) if len(s) >= 2]
    segs.sort(key=len, reverse=True)
    if not segs:
        return None
    return segs[0]  # 取最长的一个片段

samples = []
for did, info in docs.items():
    q = make_query(info["text"])
    if q:
        samples.append((did, q, info["tier"]))
samples = samples[:SAMPLE_N]
print(f"抽样 {len(samples)} 条（分 {len(tiers)} 层 tier）")

# ── 3. 四策略跑分 ──
strategies = {"FTS5-trigram单路": [], "LIKE单路": [], "RRF融合": [], "RRF+Tier(线上)": []}
lat = {k: [] for k in strategies}

for did, q, tier in samples:
    for name in strategies:
        t0 = time.perf_counter()
        if name == "FTS5-trigram单路":
            ids = fts_search(con, q, 30)
            ranked = {i: 1.0/(60+j+1) for j, i in enumerate(ids)}
        elif name == "LIKE单路":
            ids = like_search(con, q, 30)
            ranked = {i: 1.0/(60+j+1) for j, i in enumerate(ids)}
        elif name == "RRF融合":
            ranked_full = rrf_merge([fts_search(con, q, 30), like_search(con, q, 30)], limit=30)
            ranked = {i: 1.0/(60+j+1) for j, i in enumerate(ranked_full)}
        else:  # 线上真实：RRF + Tier 二次排序
            merged = rrf_merge([fts_search(con, q, 30), like_search(con, q, 30)], limit=30)
            scored = {i: 1.0/(60+j+1) for j, i in enumerate(merged)}
            final = tier_sort(scored, docs)
            ranked = {i: j+1 for j, i in enumerate(final)}  # 名次
        ms = (time.perf_counter() - t0) * 1000
        lat[name].append(ms)
        # 评测：rank 越靠前越好
        if name == "RRF+Tier(线上)":
            order = list(ranked.keys())
        else:
            order = sorted(ranked, key=lambda i: -ranked[i])
        pos = order.index(did) + 1 if did in order else None
        strategies[name].append(pos)

# ── 4. 报告 ──
def metrics(positions):
    hit5 = sum(1 for p in positions if p and p <= 5) / len(positions)
    hit10 = sum(1 for p in positions if p and p <= 10) / len(positions)
    mrr = sum(1.0 / p for p in positions if p) / len(positions)
    miss = sum(1 for p in positions if not p) / len(positions)
    return hit5, hit10, mrr, miss

print("\n" + "=" * 72)
print(f" 召回质量基准 — {datetime.now():%Y-%m-%d %H:%M} | 样本 {len(samples)} | seed=42")
print("=" * 72)
print(f"{'策略':<18}{'Hit@5':>8}{'Hit@10':>9}{'MRR':>8}{'未命中':>8}{'P95延迟':>10}")
print("-" * 72)
report = {"date": datetime.now().isoformat(), "samples": len(samples), "strategies": {}}
for name, positions in strategies.items():
    h5, h10, mrr, miss = metrics(positions)
    p95 = sorted(lat[name])[int(len(lat[name]) * 0.95) - 1]
    print(f"{name:<18}{h5:>7.1%}{h10:>8.1%}{mrr:>8.3f}{miss:>7.1%}{p95:>8.1f}ms")
    report["strategies"][name] = {"hit@5": round(h5, 4), "hit@10": round(h10, 4),
                                   "mrr": round(mrr, 4), "miss": round(miss, 4), "p95_ms": round(p95, 1)}

# 存档
out_dir = os.path.join(os.path.dirname(__file__), "..", "..", "..", "plugin_data", "astrbot_plugin_livingmemory_helper", "reports")
out_dir = os.path.abspath(out_dir)
os.makedirs(out_dir, exist_ok=True)
out = os.path.join(out_dir, f"recall_benchmark_{datetime.now():%Y%m%d_%H%M}.json")
open(out, "w", encoding="utf-8").write(json.dumps(report, ensure_ascii=False, indent=2))
print("-" * 72)
print(f"已存档: {out}")
print("注意: 伪查询=原文最长中文段（自包含线索），绝对值偏高是预期；看的是策略间相对差")
