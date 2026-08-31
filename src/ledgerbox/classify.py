from __future__ import annotations

from .parsers import Txn

ALIPAY_OFFICIAL = {
    "餐饮美食": "餐饮",
    "美食": "餐饮",
    "交通出行": "交通",
    "购物消费": "购物",
    "日用百货": "购物",
    "数码电器": "购物",
    "服饰装扮": "购物",
    "生活服务": "生活",
    "充值缴费": "生活",
    "爱车养车": "交通",
    "文化休闲": "娱乐",
    "娱乐休闲": "娱乐",
    "医疗健康": "医疗",
    "教育培训": "教育",
    "酒店旅游": "旅行",
    "转账红包": "人情",
    "亲友代付": "人情",
    "投资理财": "金融",
    "保险": "金融",
    "互助保障": "金融",
    "信用借还": "金融",
}

WECHAT_TYPE = {"红包": "人情", "微信红包": "人情", "群收款": "人情"}

MERCHANT_SEED = {
    "美团": "餐饮",
    "饿了么": "餐饮",
    "肯德基": "餐饮",
    "麦当劳": "餐饮",
    "星巴克": "餐饮",
    "瑞幸": "餐饮",
    "滴滴": "交通",
    "高德": "交通",
    "地铁": "交通",
    "淘宝": "购物",
    "天猫": "购物",
    "京东": "购物",
    "拼多多": "购物",
    "永辉": "购物",
    "房租": "居住",
    "电费": "居住",
    "Apple": "订阅",
    "iCloud": "订阅",
}


def _lookup(blob: str, table: dict[str, str]) -> str | None:
    if blob in table:
        return table[blob]
    for k, v in table.items():
        if k and k in blob:
            return v
    return None


def classify(txns: list[Txn], rules: dict[str, list[str]] | None = None) -> list[Txn]:
    extra: dict[str, str] = {}
    if rules:
        for cat, words in rules.items():
            for w in words:
                extra[w] = cat
    for t in txns:
        if t.direction == "内部转移":
            t.category = "内部转移"
            continue
        if t.direction == "收入":
            t.category = "收入"
            continue
        official = ALIPAY_OFFICIAL.get(t.raw_type)
        if official:
            t.category = official
            continue
        wx = WECHAT_TYPE.get(t.raw_type)
        if wx:
            t.category = wx
            continue
        blob = f"{t.counterparty} {t.description} {t.raw_type}"
        hit = _lookup(blob, extra) or _lookup(blob, MERCHANT_SEED)
        t.category = hit or "未分类"
    return txns
