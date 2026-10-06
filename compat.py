"""
构建期兼容补丁。

原则：**绝不修改上游源码文件**，只在内存里打补丁，这样上游更新后依旧自动生效。

补丁 1 —— anne_dictionary 缺分类会崩
    dictionary.anne_dictionary 的注释承诺「查不到会返回原文」，但实现用的是
    ANNE_DICTIONARY[catalogue] 直接索引，分类不存在时抛 KeyError。
    例如 anne_dictionary("rarity", ...) —— anne_dictionary.json 里压根没有
    "rarity" 这个分类，于是 109 条肉鸽条目的「招募/进阶希望减少」直接翻译失败。
    把 ANNE_DICTIONARY 换成 defaultdict(dict) 即可兑现它自己的契约，不涉及任何
    业务语义猜测（查不到就原样返回 "TIER_4,TIER_5,TIER_6"）。
    （上游 14f6630 重构后字典已补齐该分类，本补丁暂时是空转，保留以防再次缺类。）

补丁 2 —— AnneRelic.translate 没有兜底
    anne.py 里 AnneNode.translate 有 try/except，AnneRelic.translate 没有，
    单个藏品效果翻译失败会连累整条藏品。这里补上逐效果的降级：失败的效果显示为
    「…（翻译失败）」并平铺它的黑板数据，同一条藏品的其他效果照常翻译。

补丁 3 —— 上游 14f6630「翻译结构重构」引入的回归（CreateBuffInRange 传参错误）
    node_translator/buff.py 的 CreateBuffInRange 里把 blackboard 误传给了 list.append：
        buffs.append(analyze_buff(buff_data),blackboard)
    应为 buffs.append(analyze_buff(buff_data, blackboard))，导致相关节点整段翻译失败
    （旧版 df26933 该处写法正确）。这里只包一层：原函数能正常跑（上游已修复）就直接
    返回原结果，仍抛 TypeError 才改用修正版实现；上游修复后本补丁自动退化为空操作。
"""
import collections

import anne
import dictionary


def apply():
    """在上游模块 import 之后调用。幂等，可重复调用。"""
    # 补丁 1
    if not isinstance(dictionary.ANNE_DICTIONARY, collections.defaultdict):
        dictionary.ANNE_DICTIONARY = collections.defaultdict(dict, dictionary.ANNE_DICTIONARY)

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

    # 补丁 3
    _fix_create_buff_in_range()


def _fix_create_buff_in_range():
    """修正上游 14f6630 重构引入的 CreateBuffInRange 传参回归（见模块 docstring）。"""
    import node_translator
    import node_translator.buff as buff_mod

    if getattr(buff_mod.CreateBuffInRange, "_bena_compat", False):
        return
    original = buff_mod.CreateBuffInRange

    def CreateBuffInRange(node, blackboard):
        try:
            return original(node, blackboard)
        except TypeError:
            # 上游 bug 形态：list.append 多收了 blackboard，这里用修正版重建结果
            source_name = buff_mod.anne_dictionary("target", node["_sourceType"])
            target_name = buff_mod.anne_dictionary("target", node["_targetType"])
            target_options = buff_mod.analyze_target_options(node["_targetOptions"])
            buffs = []
            for buff_data in node["_buffs"]:
                buffs.append(buff_mod.analyze_buff(buff_data, blackboard))
            range_name = ""
            max_target = "所有"
            # 处理基本信息
            if node["_targetType"] != "BUFF_OWNER":
                range_name = f"以{target_name}为中心，"
            if node["_useHostAsSource"]:
                source_name = source_name + "(召唤物)的主人"

            if node["_limitMaxTarget"]:
                if node["_maxTargetKey"] != None:
                    max_target += f"的[{node['_maxTargetKey']}]个"
                else:
                    max_target += "的[max_target]个"
            # 处理范围信息
            if node["_useRadius"]:  # 半径制（最高优先度）
                range_name += target_name + f"半径[range_radius]（默认{node['_radius']}）内"
            elif node["_useRangeToShow"]:  # 特定模式的显示范围制
                mode_name = "当前模式" if node["_rangeModeIndex"] == -1 else f"{node['_rangeModeIndex']}号模式"
                if node["_useTargetRangeInsteadOfSource"]:
                    range_name += target_name
                else:
                    range_name += source_name
                range_name += mode_name
                if node["_rangeTargetSideType"] == "ALLY":
                    range_name += "的\"青色\"显示范围内"
                elif node["_rangeTargetSideType"] == "ENEMY":
                    range_name += "的\"橙色\"显示范围内"
                else:
                    range_name += "的显示范围内"
            elif node["_useAttackRange"]:  # 攻击范围数据制
                if node["_useTargetRangeInsteadOfSource"]:
                    range_name += target_name + "攻击范围（数据）内"
                else:
                    range_name += source_name + "攻击范围（数据）内"
            elif node["_useCurrentModeRange"]:  # 当前模式的攻击范围制
                if node["_useTargetRangeInsteadOfSource"]:
                    range_name += target_name + "当前模式的攻击范围内"
                else:
                    range_name += source_name + "当前模式的攻击范围内"
            elif node["_useGlobalRange"]:  # 全局范围
                range_name = "场上所有"
            elif node["_checkGiantTrapAllLocateTiles"]:  # 巨大装置
                range_name += target_name + "（巨型装置）占据的地块上"
            elif node["_rangeId"] != None and node["_rangeId"] != "":  # 普通范围制
                range_name += target_name + "周围" + node["_rangeId"] + "范围内"
            else:
                range_name = "周围（逻辑不明）的"
            # 部署类型额外判定
            if node["_filterByBuildableType"]:
                target_options["main"] = "部署类型为" + buff_mod.anne_dictionary("buildable_type_filter", node['_allowedBuildableType']) + "的" + target_options["main"]
            # 返回结果
            return {
                "main": f"选择{range_name}{max_target}{target_options['main']}，\"依次\"为这些单位创建以下Buff：",
                "description": f"Buff来源为{source_name}",
                "children": buffs,
            }

    CreateBuffInRange._bena_compat = True
    # AnneNode 是通过 getattr(node_translator, 节点名) 查找的，包命名空间也要替换
    buff_mod.CreateBuffInRange = CreateBuffInRange
    node_translator.CreateBuffInRange = CreateBuffInRange
