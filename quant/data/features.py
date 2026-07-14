"""
Feature Engineering Pipeline
因子工程：从原始K线/费率/OI数据提取可交易信号
"""
import math
from typing import List, Tuple, Dict, Optional


# ============================================================
# K线形态因子（零滞后）
# ============================================================

def is_bullish_engulfing(klines: List[Tuple], i: int) -> bool:
    """看涨吞没：前阴后阳，后实体包前实体"""
    if i < 1:
        return False
    prev_o, prev_c = klines[i-1][1], klines[i-1][4]
    curr_o, curr_c = klines[i][1], klines[i][4]
    return (prev_c < prev_o and curr_c > curr_o and 
            curr_o < prev_c and curr_c > prev_o)

def is_bearish_engulfing(klines: List[Tuple], i: int) -> bool:
    """看跌吞没"""
    if i < 1:
        return False
    prev_o, prev_c = klines[i-1][1], klines[i-1][4]
    curr_o, curr_c = klines[i][1], klines[i][4]
    return (prev_c > prev_o and curr_c < curr_o and 
            curr_o > prev_c and curr_c < prev_o)

def is_hammer(klines: List[Tuple], i: int) -> bool:
    """锤子线：长下影，小实体"""
    o, hi, lo, c = klines[i][1], klines[i][2], klines[i][3], klines[i][4]
    body = abs(c - o)
    wick_low = min(o, c) - lo
    wick_high = hi - max(o, c)
    total_range = max(hi - lo, 1e-12)
    return wick_low > body * 1.5 and wick_low > wick_high * 1.5 and total_range > 0

def is_shooting_star(klines: List[Tuple], i: int) -> bool:
    """射击之星：长上影"""
    o, hi, lo, c = klines[i][1], klines[i][2], klines[i][3], klines[i][4]
    body = abs(c - o)
    wick_low = min(o, c) - lo
    wick_high = hi - max(o, c)
    total_range = max(hi - lo, 1e-12)
    return wick_high > body * 1.5 and wick_high > wick_low * 1.5 and total_range > 0

def is_doji(klines: List[Tuple], i: int, prev_n: int = 10) -> bool:
    """十字星：实体极小 + 在近期低点区域"""
    o, hi, lo, c = klines[i][1], klines[i][2], klines[i][3], klines[i][4]
    body = abs(c - o)
    total_range = max(hi - lo, 1e-12)
    if body / total_range >= 0.3:
        return False
    # 是否在近期低点区域
    recent_lows = [klines[j][3] for j in range(max(0, i-prev_n), i)]
    return lo <= min(recent_lows)


def candle_score(klines: List[Tuple], i: int) -> float:
    """K线形态综合评分 0-1"""
    score = 0
    if is_hammer(klines, i): score += 0.33
    if is_bullish_engulfing(klines, i): score += 0.33
    if is_doji(klines, i): score += 0.33
    return min(score, 1.0)

def candle_score_bearish(klines: List[Tuple], i: int) -> float:
    """看跌K线形态评分"""
    score = 0
    if is_shooting_star(klines, i): score += 0.33
    if is_bearish_engulfing(klines, i): score += 0.33
    return min(score, 1.0)


# ============================================================
# 量价关系因子
# ============================================================

def volume_surge_ratio(klines: List[Tuple], i: int, lookback: int = 20) -> float:
    """放量倍数"""
    if i < lookback:
        return 1.0
    vol = klines[i][5]
    avg_vol = sum(klines[j][5] for j in range(i-lookback, i)) / lookback
    return vol / avg_vol if avg_vol > 0 else 1.0

def volume_score(klines: List[Tuple], i: int) -> float:
    """量价评分：放量阳线=多头进场信号"""
    o, c, v = klines[i][1], klines[i][4], klines[i][5]
    lookback = 20
    if i < lookback:
        return 0
    avg_vol = sum(klines[j][5] for j in range(i-lookback, i)) / lookback
    if avg_vol == 0:
        return 0
    ratio = v / avg_vol
    is_bullish = c > o
    # 放量阳线得分高，缩量阴线得分低
    if is_bullish and ratio > 1.5:
        return min(ratio / 3, 1.0)
    return 0

def volume_score_bearish(klines: List[Tuple], i: int) -> float:
    """看跌量价评分"""
    o, c, v = klines[i][1], klines[i][4], klines[i][5]
    lookback = 20
    if i < lookback:
        return 0
    avg_vol = sum(klines[j][5] for j in range(i-lookback, i)) / lookback
    if avg_vol == 0:
        return 0
    ratio = v / avg_vol
    is_bearish = c < o
    if is_bearish and ratio > 1.5:
        return min(ratio / 3, 1.0)
    return 0


# ============================================================
# 价格行为因子
# ============================================================

def sma(klines: List[Tuple], i: int, period: int = 20) -> float:
    """简单移动平均"""
    start = max(0, i - period)
    closes = [klines[j][4] for j in range(start, i+1)]
    return sum(closes) / len(closes)

def ema(values: List[float], period: int) -> List[float]:
    """指数移动平均"""
    if len(values) < period:
        return [sum(values)/len(values)] * len(values)
    result = [sum(values[:period]) / period]
    multiplier = 2 / (period + 1)
    for v in values[period:]:
        result.append((v - result[-1]) * multiplier + result[-1])
    return result

def at_support(klines: List[Tuple], i: int, lookback: int = 20) -> float:
    """是否在近期支撑位 (±1%)"""
    if i < lookback:
        return 0
    lo = min(klines[j][3] for j in range(i-lookback, i))
    c = klines[i][4]
    dist = abs(c - lo) / max(lo, 1e-12)
    return 1.0 if dist < 0.01 else 0

def at_resistance(klines: List[Tuple], i: int, lookback: int = 20) -> float:
    """是否在近期阻力位"""
    if i < lookback:
        return 0
    hi = max(klines[j][2] for j in range(i-lookback, i))
    c = klines[i][4]
    dist = abs(c - hi) / max(hi, 1e-12)
    return 1.0 if dist < 0.01 else 0

def pullback_depth(klines: List[Tuple], i: int, lookback: int = 20) -> float:
    """回调深度（从近期高点）"""
    if i < lookback:
        return 0
    hi = max(klines[j][2] for j in range(i-lookback, i))
    c = klines[i][4]
    return (hi - c) / max(hi, 1e-12)

def pa_score(klines: List[Tuple], i: int) -> float:
    """价格行为评分：支撑位+均线上方+健康回调"""
    c = klines[i][4]
    sma20 = sma(klines, i, 20)
    pb = pullback_depth(klines, i, 20)
    
    score = 0
    if at_support(klines, i, 20):
        score += 0.33
    if c > sma20:
        score += 0.33
    if 0.03 < pb < 0.20:  # 健康回调3-20%
        score += 0.33
    return score

def pa_score_bearish(klines: List[Tuple], i: int) -> float:
    """看跌价格行为评分"""
    c = klines[i][4]
    sma20 = sma(klines, i, 20)
    
    score = 0
    if at_resistance(klines, i, 20):
        score += 0.33
    if c < sma20:
        score += 0.33
    if pullback_depth(klines, i, 20) < 0.03 and c < klines[i-1][4]:
        score += 0.33
    return score


# ============================================================
# 趋势因子
# ============================================================

def trend_score(klines: List[Tuple], i: int) -> float:
    """趋势评分：均线多头排列 + 价格位置"""
    if i < 50:
        return 0
    c = klines[i][4]
    sma20 = sma(klines, i, 20)
    sma50 = sma(klines, i, 50)
    
    if c > sma20 > sma50:
        return 1.0
    elif c > sma20:
        return 0.5
    elif c > sma50:
        return 0.3
    return 0

def trend_score_bearish(klines: List[Tuple], i: int) -> float:
    """看跌趋势评分"""
    if i < 50:
        return 0
    c = klines[i][4]
    sma20 = sma(klines, i, 20)
    sma50 = sma(klines, i, 50)
    
    if c < sma20 < sma50:
        return 1.0
    elif c < sma20:
        return 0.5
    elif c < sma50:
        return 0.3
    return 0


# ============================================================
# 费率因子
# ============================================================

def get_funding_at_time(funding_rates: List[Tuple], target_ms: int) -> float:
    """获取指定时间的费率"""
    if not funding_rates:
        return 0
    # funding_rates: [(time_ms, rate), ...]
    # 找到 <= target_ms 的最新费率
    best = 0
    best_time = 0
    for t, r in funding_rates:
        if t <= target_ms and t > best_time:
            best = r
            best_time = t
    return best

def funding_extreme_score(funding_rates: List[Tuple], current_ms: int, 
                          threshold: float = -0.0005) -> float:
    """
    费率极端位评分
    费率极度负值 → 空头过度拥挤 → 做多机会
    """
    fr = get_funding_at_time(funding_rates, current_ms)
    if fr < threshold:
        # 费率越负，分数越高
        return min(abs(fr) / abs(threshold * 4), 1.0)
    return 0

def funding_extreme_short_score(funding_rates: List[Tuple], current_ms: int,
                                threshold: float = 0.0005) -> float:
    """费率极端正值 → 多头过度拥挤 → 做空机会"""
    fr = get_funding_at_time(funding_rates, current_ms)
    if fr > threshold:
        return min(fr / (threshold * 4), 1.0)
    return 0


# ============================================================
# OI 背离因子
# ============================================================

def oi_divergence_score(klines: List[Tuple], oi_data: List[Tuple], i: int,
                        lookback: int = 10) -> float:
    """
    OI背离评分
    价格跌 + OI涨 = 机构吸筹（做多信号）
    价格涨 + OI跌 = 多头平仓（做空信号）
    """
    if not oi_data or i < lookback:
        return 0
    
    # 简化：用K线近几根的价格方向和OI方向
    price_change = (klines[i][4] - klines[i-lookback][4]) / max(klines[i-lookback][4], 1e-12)
    
    # 找最近的OI
    oi_current = None
    oi_past = None
    current_ms = klines[i][0]
    past_ms = klines[i-lookback][0]
    
    for t, oi in oi_data:
        if t <= current_ms and (oi_current is None or t > oi_current_time):
            oi_current = oi
            oi_current_time = t
    
    oi_past_time = 0
    for t, oi in oi_data:
        if t <= past_ms and t > oi_past_time:
            oi_past = oi
            oi_past_time = t
    
    if oi_current and oi_past and oi_past > 0:
        oi_change = (oi_current - oi_past) / oi_past
        
        # 价格跌 + OI涨 → 做多信号
        if price_change < -0.01 and oi_change > 0.01:
            return min(abs(price_change) * 20 + oi_change * 10, 1.0)
        # 价格涨 + OI跌 → 做空信号（暂未实现做空）
    
    return 0


# ============================================================
# 波动率因子
# ============================================================

def atr(klines: List[Tuple], i: int, period: int = 14) -> float:
    """Average True Range"""
    if i < period:
        return 0
    tr_sum = 0
    for j in range(i - period + 1, i + 1):
        hi, lo = klines[j][2], klines[j][3]
        prev_c = klines[j-1][4]
        tr = max(hi - lo, abs(hi - prev_c), abs(lo - prev_c))
        tr_sum += tr
    return tr_sum / period

def volatility_regime(klines: List[Tuple], i: int, period: int = 20) -> str:
    """
    波动率状态分类
    Returns: 'LOW' | 'NORMAL' | 'HIGH' | 'EXTREME'
    """
    if i < period * 2:
        return 'NORMAL'
    
    current_atr = atr(klines, i, period)
    past_atr = atr(klines, i - period, period)
    
    if past_atr == 0:
        return 'NORMAL'
    
    ratio = current_atr / past_atr
    if ratio < 0.7:
        return 'LOW'
    elif ratio < 1.3:
        return 'NORMAL'
    elif ratio < 2.0:
        return 'HIGH'
    else:
        return 'EXTREME'


# ============================================================
# 复合因子评分
# ============================================================

def multifactor_score(klines: List[Tuple], i: int, 
                      funding_rates: List[Tuple] = None,
                      oi_data: List[Tuple] = None,
                      weights: Dict[str, float] = None) -> Tuple[float, dict]:
    """
    多因子综合评分
    
    Returns:
        (total_score, factor_details)
    """
    if weights is None:
        weights = {'candle': 0.2, 'vol': 0.4, 'pa': 0.3, 'trend': 0.1}
    
    cn = candle_score(klines, i)
    vl = volume_score(klines, i)
    pa = pa_score(klines, i)
    tr = trend_score(klines, i)
    
    details = {'candle': round(cn, 2), 'vol': round(vl, 2), 
               'pa': round(pa, 2), 'trend': round(tr, 2)}
    
    # 加入费率因子（如果有数据）
    if funding_rates:
        fr = funding_extreme_score(funding_rates, klines[i][0])
        details['funding'] = round(fr, 2)
        # 动态调整权重：费率极端时加大权重
        w = weights.copy()
        if fr > 0.5:
            w = {'candle': 0.15, 'vol': 0.25, 'pa': 0.2, 'trend': 0.1, 'funding': 0.3}
            score = cn*0.15 + vl*0.25 + pa*0.2 + tr*0.1 + fr*0.3
        else:
            score = cn*weights['candle'] + vl*weights['vol'] + pa*weights['pa'] + tr*weights['trend']
    else:
        score = cn*weights['candle'] + vl*weights['vol'] + pa*weights['pa'] + tr*weights['trend']
    
    # OI背离加分
    if oi_data:
        oi = oi_divergence_score(klines, oi_data, i)
        if oi > 0.5:
            score = min(score + 0.1, 1.0)
            details['oi'] = round(oi, 2)
    
    return round(score, 3), details


def btc_filter(btc_klines: List[Tuple], i: int = -1, 
               crash_threshold: float = -0.05) -> bool:
    """
    BTC崩盘过滤器
    如果BTC 24h跌幅超过阈值，禁止做多
    """
    if not btc_klines or len(btc_klines) < 288:  # 24h of 5m = 288 bars
        return True  # 数据不足，允许交易
    
    if i < 0:
        i = len(btc_klines) - 1
    if i < 288:
        return True
    
    current = btc_klines[i][4]
    past = btc_klines[i-288][4]
    if past > 0:
        chg = (current - past) / past
        return chg > crash_threshold
    
    return True
