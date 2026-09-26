"""
构建期兼容补丁。

原则：**绝不修改上游源码文件**，只在内存里打补丁，这样上游更新后依旧自动生效。

补丁 1 —— anne_dictionary 缺分类会崩
    translator.anne_dictionary 的注释承诺「查不到会返回原文」，但实现用的是
    ANNE_DICTIONARY[catalogue] 直接索引，分类不存在时抛 KeyError。
    例如 anne_dictionary("rarity", ...) —— anne_dictionary.json 里压根没有
    "rarity" 这个分类，于是 109 条肉鸽条目的「招募/进阶希望减少」直接翻译失败。
    把 ANNE_DICTIONARY 换成 defaultdict(dict) 即可兑现它自己的契约，不涉及任何
    业务语义猜测（查不到就原样返回 "TIER_4,TIER_5,TIER_6"）。

补丁 2 —— AnneRelic.translate 没有兜底
    anne.py 里 AnneNode.translate 有 try/except，AnneRelic.translate 没有，
    单个藏品效果翻译失败会连累整条藏品。这里补上逐效果的降级：失败的效果显示为
    「…（翻译失败）」并平铺它的黑板数据，同一条藏品的其他效果照常翻译。
"""
import collections

import anne
import translator


def apply():
    """在上游模块 import 之后调用。幂等，可重复调用。"""
    # 补丁 1
    if not isinstance(translator.ANNE_DICTIONARY, collections.defaultdict):
        translator.ANNE_DICTIONARY = collections.defaultdict(dict, translator.ANNE_DICTIONARY)

    # 补丁 2
    if not getattr(anne.AnneRelic.translate, "_bena_compat", False):
        original = anne.AnneRelic.translate

        def translate(self, rogue_effect):
            try:
                return original(self, rogue_effect)
            except Exception as e:
                if rogue_effect.translation is None:
                    children = [
                        {"main": str(k) + " : " + str(v)}
                        for k, v in (rogue_effect.blackboard or {}).items()
                    ]
                    rogue_effect.translation = {
                        "main": "%s（翻译失败：%s）" % (rogue_effect.key, type(e).__name__),
                        "style_closed": True,
                        "children": children,
                    }
                    self._last_error = e
                return rogue_effect.translation

        translate._bena_compat = True
        anne.AnneRelic.translate = translate
