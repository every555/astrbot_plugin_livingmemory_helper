"""
emotion_engine.py — v5.7 上下文感知情感引擎（cnsenti增强版）
借鉴 meme_manager 的 _is_likely_emotion_markup 上下文扫描思路，
实现多粒度、上下文感知的情感分析。

特性：
1. 否定词反转检测（"不高兴" → 负面）
2. 转折词后半句权重提升（递归分句，"虽然不开心但搞定了" → 取后半句）
3. 程度副词强度调节（超/非常/有点）
4. 多粒度情感分类（11种细分情绪）
5. 对话角色感知（用户 vs AI）
6. cnsenti增强词典（dutir七情 + hownet，2090词）
"""

import re
import os
import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ━━━ 基础情感词典（内置 fallback）━━━

_BASE_EMOTION_LEXICON: dict[str, list[str]] = {
    # ── 正面 ──
    "happy": ["开心", "高兴", "快乐", "嘻嘻", "哈哈", "嘿嘿", "(≧▽≦)", "૮₍˶•ᴗ•˶₎ა", "٩(◕‿◕｡)۶", "超开心", "愉快", "舒心", "满意", "幸福", "甜蜜", "欣慰", "惬意", "舒畅", "欢喜", "美滋滋", "想你", "💕", "🥰", "😘", "❤️"],
    "excited": ["兴奋", "激动", "太棒了", "牛", "厉害", "哇", "卧槽", "草", "我去", "震撼", "惊艳"],
    "proud": ["完成", "成功", "搞定", "通过了", "全过", "解决", "修好了", "升级完成", "实现"],
    "grateful": ["谢谢", "感谢", "辛苦了", "多亏", "劳烦", "靠谱", "给力"],
    # ── 负面 ──
    "frustrated": ["失败", "bug", "报错", "不行", "做不到", "搞不定", "崩溃", "炸了", "寄了", "挫败", "受挫", "碰壁", "卡住", "卡壳", "一团糟", "乱套", "完蛋", "糟糕", "搞砸", "白费"],
    "sad": ["难过", "伤心", "失落", "失望", "郁闷", "emo", "想哭", "心累", "忧伤", "悲哀", "惆怅", "惘然", "黯然", "凄凉", "孤独", "寂寞", "落寞", "心痛", "心碎", "惋惜"],
    "anxious": ["担心", "焦虑", "紧张", "怕", "害怕", "不确定", "没底", "慌", "惶恐", "惶惶", "忐忑", "不安", "畏惧", "胆怯", "怯场", "发怵", "心慌", "心虚", "疑虑", "顾虑"],
    "angry": ["生气", "烦", "讨厌", "恶心", "过分", "无语", "操", "靠", "妈的", "shit", "愤怒", "恼火", "气愤", "恼怒", "暴怒", "怒火", "可恶", "可恨", "气死", "抓狂"],
    # ── 中性 ──
    "calm": ["还行", "好的", "嗯", "哦", "了解", "知道", "明白", "收到"],
    "focused": ["分析", "研究", "调试", "排查", "定位", "测试", "实现", "编码", "写代码"],
    "tired": ["累", "困", "困死了", "熬夜", "通宵", "睡", "休息", "撑不住", "顶不住"],
}

_BASE_NEGATION_WORDS = ["不", "没", "别", "无", "非", "未", "莫", "勿", "毫不", "并不", "不太"]

# 转折词（后半句权重 ×2，前半句权重 ×0.3）
TRANSITION_WORDS = ["但", "但是", "不过", "然而", "可是", "虽然", "尽管", "只是", "其实"]

_BASE_INTENSITY_MODIFIERS = {
    "超": 1.5, "非常": 1.4, "特别": 1.4, "极其": 1.5, "太": 1.3,
    "真的": 1.2, "好": 1.2, "贼": 1.3, "巨": 1.3,
    "有点": 0.6, "稍微": 0.5, "略": 0.5, "勉强": 0.4,
    "又": 1.2, "再": 1.1, "还": 1.1,
}


def _load_enhanced_lexicon():
    """
    从 dictionaries/emotion_lexicon.json 加载增强版词典。
    如果文件不存在或加载失败，回退到内置基础词典。
    
    数据来源：cnsenti (dutir七情词典 + hownet情感词典)
    """
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    lexicon_path = os.path.join(base_dir, "dictionaries", "emotion_lexicon.json")
    
    try:
        if not os.path.exists(lexicon_path):
            logger.info("[EmotionEngine] 增强词典不存在，使用基础词典")
            return dict(_BASE_EMOTION_LEXICON), list(_BASE_NEGATION_WORDS), dict(_BASE_INTENSITY_MODIFIERS)
        
        with open(lexicon_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        lexicon = data.get("lexicon", {})
        negations = data.get("negations", [])
        intensities = data.get("intensities", {})
        
        # 合并：基础词典的词优先保留（它们是精选的高质量词）
        merged_lexicon = {}
        for emo, base_words in _BASE_EMOTION_LEXICON.items():
            enhanced = set(lexicon.get(emo, []))
            for w in base_words:
                enhanced.add(w)
            merged_lexicon[emo] = sorted(enhanced)
        
        merged_negations = list(set(negations + _BASE_NEGATION_WORDS))
        
        merged_intensities = dict(_BASE_INTENSITY_MODIFIERS)
        for w, mult in intensities.items():
            if w not in merged_intensities:
                merged_intensities[w] = mult
        
        total = sum(len(v) for v in merged_lexicon.values())
        logger.info(f"[EmotionEngine] 增强词典加载成功: {total} 情感词, "
                     f"{len(merged_intensities)} 程度副词, {len(merged_negations)} 否定词")
        return merged_lexicon, merged_negations, merged_intensities
        
    except Exception as e:
        logger.warning(f"[EmotionEngine] 增强词典加载失败({e})，回退基础词典")
        return dict(_BASE_EMOTION_LEXICON), list(_BASE_NEGATION_WORDS), dict(_BASE_INTENSITY_MODIFIERS)


# ━━━ 加载词典（启动时执行一次）━━━

EMOTION_LEXICON, NEGATION_WORDS, INTENSITY_MODIFIERS = _load_enhanced_lexicon()

# 情感极性映射（用于趋势统计的兼容）
EMOTION_POLARITY: dict[str, str] = {
    "happy": "positive", "excited": "positive", "proud": "positive", "grateful": "positive",
    "frustrated": "negative", "sad": "negative", "anxious": "negative", "angry": "negative",
    "calm": "neutral", "focused": "neutral", "tired": "neutral",
    "neutral": "neutral",
}


class EmotionEngine:
    """上下文感知情感分析引擎"""

    def __init__(self):
        # 预编译正则：匹配情感词前2字符窗口内的否定词
        self._negation_pattern = re.compile(
            r"(?:" + "|".join(re.escape(w) for w in NEGATION_WORDS) + r")\s{0,2}(\S{0,3})$"
        )
        logger.info(f"[EmotionEngine] v5.7 上下文感知情感引擎已初始化，"
                     f"{len(EMOTION_LEXICON)}类情绪，{sum(len(v) for v in EMOTION_LEXICON.values())}情感词")

    def analyze(self, text: str, speaker: str = "user") -> dict:
        """
        分析文本的情感。

        Args:
            text: 待分析文本
            speaker: 说话角色 "user" 或 "ai"

        Returns:
            {
                "emotion": "happy",         # 细粒度情绪标签
                "sentiment": "positive",    # 极性（兼容旧字段）
                "intensity": 0.85,          # 强度 0~1
                "confidence": 0.7,          # 置信度 0~1
                "speaker": "user",          # 说话角色
                "detail": {                 # 调试详情
                    "matched": [("开心", "happy", 1.5, "+")],
                    "negated": [],
                    "transition_split": "但",
                }
            }
        """
        if not text or not text.strip():
            return self._empty_result(speaker)

        # 清理文本（保留标点用于分句）
        clean = text.strip()
        # 去除 markdown 格式符号
        clean = re.sub(r"[*_`#>|]+", "", clean)

        # ── Step 1: 转折词分句 ──
        segments = self._split_by_transition(clean)

        # ── Step 2: 逐段匹配情感词 ──
        all_matches: list[tuple[str, str, float]] = []  # (word, emotion, intensity)
        negated_words: list[str] = []

        for seg_text, seg_weight in segments:
            matches = self._match_emotions_in_segment(seg_text, seg_weight)
            for word, emotion, intensity, is_negated in matches:
                if is_negated:
                    negated_words.append(word)
                    # 反转极性：正面→负面，负面→正面
                    polarity = EMOTION_POLARITY.get(emotion, "neutral")
                    flipped = self._flip_emotion(emotion) if polarity != "neutral" else emotion
                    if flipped != emotion:
                        all_matches.append((word, flipped, intensity * 0.8))
                else:
                    all_matches.append((word, emotion, intensity))

        if not all_matches:
            return self._empty_result(speaker, fallback="neutral")

        # ── Step 3: 加权汇总 ──
        emotion_scores: dict[str, float] = {}
        for word, emotion, intensity in all_matches:
            emotion_scores[emotion] = emotion_scores.get(emotion, 0) + intensity

        # 取最高分情绪
        best_emotion = max(emotion_scores, key=emotion_scores.get)
        best_score = emotion_scores[best_emotion]
        total_score = sum(emotion_scores.values())

        # 强度归一化（0~1）
        intensity = min(1.0, best_score / 3.0)

        # 置信度：最高分占比 × 词数因子
        confidence = (best_score / total_score) if total_score > 0 else 0
        confidence = min(1.0, confidence * (1 + 0.1 * min(len(all_matches), 3)))

        # 极性
        sentiment = EMOTION_POLARITY.get(best_emotion, "neutral")

        result = {
            "emotion": best_emotion,
            "sentiment": sentiment,
            "intensity": round(intensity, 2),
            "confidence": round(confidence, 2),
            "speaker": speaker,
            "detail": {
                "matched": [(w, e, s) for w, e, s in all_matches],
                "negated": negated_words,
                "segments": [(s[0], s[1]) for s in segments],
                "scores": emotion_scores,
            }
        }

        logger.debug(f"[EmotionEngine] 分析结果: {best_emotion}({sentiment}) "
                     f"强度={intensity:.2f} 置信={confidence:.2f} "
                     f"否定词={negated_words} 匹配数={len(all_matches)}")
        return result

    def _split_by_transition(self, text: str, parent_weight: float = 1.0) -> list[tuple[str, float]]:
        """
        按转折词分句，返回 (文本, 权重) 列表。
        转折词后半句权重 ×2，前半句权重 ×0.3。
        递归处理：after 段中如果还有转折词，继续分句。
        """
        # 找到第一个转折词的位置
        best_pos = -1
        best_word = None
        for word in TRANSITION_WORDS:
            pos = text.find(word)
            if pos >= 0 and (best_pos < 0 or pos < best_pos):
                best_pos = pos
                best_word = word

        if best_pos < 0:
            return [(text, parent_weight)]

        before = text[:best_pos].strip()
        after = text[best_pos + len(best_word):].strip()

        segments = []
        if before:
            segments.append((before, parent_weight * 0.3))  # 转折前权重低
        if after:
            # 递归处理 after 段，权重 ×2
            sub_segments = self._split_by_transition(after, parent_weight * 2.0)
            segments.extend(sub_segments)
        else:
            # "但" 后面没内容了，前半句恢复正常权重
            if before:
                segments = [(before, parent_weight)]
        return segments

    def _match_emotions_in_segment(self, text: str, weight: float) -> list[tuple[str, str, float, bool]]:
        """
        在文本段中匹配情感词，返回 (word, emotion, intensity, is_negated)。
        
        借鉴 meme_manager 的 _is_likely_emotion：
        - 扫描情感词前2字符窗口检查否定词
        - 扫描情感词前3字符窗口检查程度副词
        """
        results: list[tuple[str, str, float, bool]] = []

        for emotion, words in EMOTION_LEXICON.items():
            for word in words:
                # 找到所有出现位置
                start = 0
                while True:
                    pos = text.find(word, start)
                    if pos < 0:
                        break

                    # ── 检查程度副词 ──
                    intensity_mod = 1.0
                    prefix = text[max(0, pos - 3):pos]
                    for mod_word, mod_val in INTENSITY_MODIFIERS.items():
                        if mod_word in prefix:
                            intensity_mod *= mod_val
                            break

                    # ── 检查否定词（前2字符窗口）──
                    prefix_neg = text[max(0, pos - 2):pos]
                    is_negated = any(neg in prefix_neg for neg in NEGATION_WORDS)

                    # 计算最终强度
                    final_intensity = weight * intensity_mod

                    results.append((word, emotion, final_intensity, is_negated))

                    start = pos + len(word)

        return results

    def _flip_emotion(self, emotion: str) -> str:
        """反转情绪极性：正面↔负面"""
        flip_map = {
            "happy": "sad",
            "excited": "anxious",
            "proud": "frustrated",
            "grateful": "angry",
            "frustrated": "proud",
            "sad": "happy",
            "anxious": "excited",
            "angry": "grateful",
        }
        return flip_map.get(emotion, emotion)

    def _empty_result(self, speaker: str, fallback: str = "neutral") -> dict:
        return {
            "emotion": fallback,
            "sentiment": EMOTION_POLARITY.get(fallback, "neutral"),
            "intensity": 0.0,
            "confidence": 0.0,
            "speaker": speaker,
            "detail": {
                "matched": [],
                "negated": [],
                "segments": [],
                "scores": {},
            }
        }

    def get_recent_trend(self, emotions: list[dict]) -> dict:
        """
        分析最近N条记忆的情感趋势。
        
        Args:
            emotions: [{"emotion": "happy", "sentiment": "positive", "intensity": 0.8}, ...]

        Returns:
            {
                "dominant": "happy",        # 主导情绪
                "polarity": "positive",     # 整体极性
                "avg_intensity": 0.65,      # 平均强度
                "trend": "rising",          # rising / falling / stable
                "distribution": {"happy": 3, "frustrated": 1, ...},
            }
        """
        if not emotions:
            return {"dominant": "neutral", "polarity": "neutral",
                    "avg_intensity": 0.0, "trend": "stable", "distribution": {}}

        distribution: dict[str, int] = {}
        polarities: dict[str, int] = {"positive": 0, "negative": 0, "neutral": 0}
        intensities: list[float] = []

        for item in emotions:
            emo = item.get("emotion", "neutral")
            pol = item.get("sentiment", "neutral")
            dist = item.get("intensity", 0.5)

            distribution[emo] = distribution.get(emo, 0) + 1
            polarities[pol] = polarities.get(pol, 0) + 1
            intensities.append(dist)

        # 主导情绪
        dominant = max(distribution, key=distribution.get) if distribution else "neutral"

        # 整体极性
        if polarities["positive"] > polarities["negative"]:
            polarity = "positive"
        elif polarities["negative"] > polarities["positive"]:
            polarity = "negative"
        else:
            polarity = "neutral"

        # 趋势方向（前半段 vs 后半段平均强度）
        avg_intensity = sum(intensities) / len(intensities) if intensities else 0
        if len(intensities) >= 4:
            mid = len(intensities) // 2
            first_half = sum(intensities[:mid]) / mid
            second_half = sum(intensities[mid:]) / (len(intensities) - mid)
            if second_half > first_half * 1.15:
                trend = "rising"
            elif second_half < first_half * 0.85:
                trend = "falling"
            else:
                trend = "stable"
        else:
            trend = "stable"

        return {
            "dominant": dominant,
            "polarity": polarity,
            "avg_intensity": round(avg_intensity, 2),
            "trend": trend,
            "distribution": distribution,
        }
