# -*- coding: utf-8 -*-
"""MMR 多样性重排单测 — trigram/jaccard/贪心选择/归一化/边界"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.rrf_engine import trigram_set, jaccard, mmr_rerank


def test_trigram_basic():
    g = trigram_set("橘子真可爱")
    assert g == {"橘子真", "子真可", "真可爱"}
    assert trigram_set("ab") == {"ab"}
    assert trigram_set("") == set()
    assert trigram_set(None) == set()


def test_jaccard():
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a"}, {"b"}) == 0.0
    v = jaccard({"a", "b", "c"}, {"a", "b", "d"})
    assert abs(v - 2 / 4) < 1e-9
    assert jaccard(set(), {"a"}) == 0.0


def test_mmr_lam1_pure_relevance():
    """lam=1 → 纯相关性排序，等同原序"""
    items = [
        {"id": 1, "text": "今天橘子背了五十个英语单词", "_rrf_score": 0.03},
        {"id": 2, "text": "今天橘子背了五十个英语单词哦", "_rrf_score": 0.02},
        {"id": 3, "text": "樱花流场调色盘改成了金色", "_rrf_score": 0.01},
    ]
    out = mmr_rerank(items, limit=3, lam=1.0)
    assert [x["id"] for x in out] == [1, 2, 3]


def test_mmr_similarity_yields():
    """默认 lam：高相关的重复文本会让位给多样的第三条（核心价值）"""
    items = [
        {"id": 1, "text": "橘子晚上十点开始陪我测语音链路樱花音色", "_rrf_score": 0.030},
        {"id": 2, "text": "橘子晚上十点开始陪我测语音链路樱花音色第二版", "_rrf_score": 0.029},  # 与#1高度重复
        {"id": 3, "text": "周六全家去超市买了玉米粒和土豆丝", "_rrf_score": 0.020},  # 多样
    ]
    out = mmr_rerank(items, limit=2, lam=0.7)
    ids = [x["id"] for x in out]
    assert 3 in ids, "多样性条目应挤掉重复条目"
    assert 1 in ids, "最高相关必留"
    assert ids[0] == 1


def test_mmr_lam0_disabled():
    """lam=0 → 关闭：直接原序截断，不重排"""
    items = [
        {"id": i, "text": "文本" + str(i), "_rrf_score": 0.03 - i * 0.001} for i in range(1, 6)
    ]
    out = mmr_rerank(items, limit=3, lam=0.0)
    assert [x["id"] for x in out] == [1, 2, 3]
    assert "_mmr_rank" not in out[0], "关闭时不应打标"


def test_mmr_rel_key_priority():
    """rel_key 指定字段 > _final > _rrf_score"""
    items = [
        {"id": 1, "text": "甲乙丙丁戊己庚", "_final": 0.9, "_rrf_score": 0.01},
        {"id": 2, "text": "子丑寅卯辰巳午", "_final": 0.1, "_rrf_score": 0.05},
    ]
    out = mmr_rerank(items, limit=2, lam=1.0)
    assert [x["id"] for x in out] == [1, 2], "_final 应优先于 _rrf_score"
    out2 = mmr_rerank(items, limit=2, lam=1.0, rel_key="_rrf_score")
    assert [x["id"] for x in out2] == [2, 1], "rel_key 显式指定时用它"


def test_mmr_pool_smaller_than_limit():
    items = [{"id": 1, "text": "只有一条", "_rrf_score": 0.02}]
    out = mmr_rerank(items, limit=5, lam=0.7)
    assert len(out) == 1 and out[0]["id"] == 1


def test_mmr_all_same_relevance():
    """全同分（span=0 防除零）→ 退化为纯多样性选择，不炸"""
    items = [
        {"id": 1, "text": "苹果香蕉梨子", "_rrf_score": 0.01},
        {"id": 2, "text": "苹果香蕉梨子", "_rrf_score": 0.01},
        {"id": 3, "text": "火车飞机轮船", "_rrf_score": 0.01},
    ]
    out = mmr_rerank(items, limit=2, lam=0.7)
    assert len(out) == 2
    assert out[0]["id"] == 1 and out[1]["id"] == 3, "同分时第二条应选多样而非重复"


def test_mmr_rank_marker():
    items = [
        {"id": i, "text": f"完全不同内容{chr(64+i)}号", "_rrf_score": 0.05 - i * 0.01} for i in range(1, 4)
    ]
    out = mmr_rerank(items, limit=3, lam=0.7)
    assert [x.get("_mmr_rank") for x in out] == [0, 1, 2]
