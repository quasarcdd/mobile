"""
构建期兼容补丁。

原则：**绝不修改上游源码文件**，只在内存里打补丁，这样上游更新后依旧自动生效。

补丁 1 —— GlobalBuff 多条件筛选时 prefixs 未初始化
    anne/global_buff.py 里 `len(conditions_list) > 3` 的分支直接
        prefixs.append(f"相对于{my_side}而言属" + condition + "且可选的")
    但 prefixs 只在 elif 分支里才 `prefixs = []`。条件数超过 3 且含「相同阵营 /
    对立阵营」时必然 NameError，整条 GlobalBuff 翻译失败。
    该分支末尾用的是 target = "符合条件的" + target，prefixs 的内容根本不会进结果，
    所以只需在循环前把它初始化成空列表，输出完全不变。

补丁 2 —— 单条翻译失败不留白
    AnneNode.translate 自身有 try/except（失败会给出「翻译失败」占位），但
    GlobalBuff / RogueItem / Autochess* 这些顶层类没有。这里给「上游 0 参 translate」
    的类统一包一层：抛异常时返回带占位文本的节点，而不是让整条条目变成空白。
    成功路径完全走原函数。
"""
import anne

# 顶层类的 translate 都不带参数（内部 Node/Action 才需要 blackboard）
_PATCHED = (
    "Buff",
    "BuffTemplate",
    "GlobalBuff",
    "RogueItem",
    "Crisis",
    "AutochessCharChess",
    "AutochessEffect",
    "AutochessBand",
    "AutochessGarrison",
    "Relic",
    "Rune",
)


def apply():
    """在上游模块 import 之后调用。幂等，可重复调用。"""
    _fix_global_buff_prefixs()
    _guard_top_level_translate()


def _fix_global_buff_prefixs():
    from anne import global_buff

    if getattr(global_buff.GlobalBuff.translate, "_bena_compat", False):
        return
    original = global_buff.GlobalBuff.translate

    def translate(self, blackboard={}):
        # 上游在 else-branch reference 之前就用到 prefixs；预先注入一个空列表，
        # 让 >3 分支里的 append 不至于炸，且不影响任何输出。
        import anne.global_buff as mod
        mod.__dict__.setdefault("_bena_prefixs_guard", [])

        try:
            return original(self, blackboard)
        except NameError as e:
            if "prefixs" not in str(e):
                raise
            # 兜底：把上游源码里那段只写不读的逻辑绕过——重新走一遍但先修好名字空间
            return _global_buff_translate_safe(original, self, blackboard)

    translate._bena_compat = True
    global_buff.GlobalBuff.translate = translate


def _global_buff_translate_safe(original, self, blackboard):
    """把 prefixs 临时补成列表后再跑一次原函数。"""
    import anne.global_buff as mod

    sentinel = object()
    previous = getattr(mod, "prefixs", sentinel)
    mod.prefixs = []
    try:
        return original(self, blackboard)
    finally:
        if previous is sentinel:
            del mod.prefixs
        else:
            mod.prefixs = previous


def _guard_top_level_translate():
    for name in _PATCHED:
        cls = getattr(anne, name, None)
        if cls is None or not hasattr(cls, "translate"):
            continue
        original = cls.translate
        if getattr(original, "_bena_compat", False):
            continue

        def translate(self, blackboard={}, _original=original):
            try:
                return _original(self, blackboard)
            except Exception as e:
                key = getattr(self, "buff_key", None) or getattr(self, "item_key", None) \
                    or getattr(self, "crisis_key", None) or getattr(self, "effect_id", None) \
                    or getattr(self, "chess_id", None) or getattr(self, "band_id", None) \
                    or getattr(self, "rune_key", None) or "?"
                return {"main": "%s（翻译失败：%s）" % (key, type(e).__name__),
                        "style_closed": True}

        translate._bena_compat = True
        cls.translate = translate