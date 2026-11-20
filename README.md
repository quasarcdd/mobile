# 《贝娜的量角器》手机版

把 [TeamTorappu/BenaProtractor](https://github.com/TeamTorappu/BenaProtractor) 的翻译结果预先算好，
打包成一个自包含的 HTML 文件，手机浏览器直接打开就能检索、阅读。

线上地址：<https://quasarcdd.github.io/mobile/>

## 工作原理

手机浏览器里没有 Python，跑不了 bena 那套翻译规则。所以放在 GitHub Actions 上：

```
Actions 定时 → 拉上游 Python 规则 + 鹰角游戏数据 → 在云端跑一遍翻译引擎
            → 产出 gzip 数据包 → 内联进 HTML → 发布到 GitHub Pages
```

手机端只负责解压、检索和渲染，不做任何翻译计算。构建产物是**单个 HTML 文件**：
数据以 base64(gzip(JSON)) 的形式内联在 `<script id="payload">` 里，用 `fflate` 解压，
CSP 收紧为 `connect-src 'none'`，**打开后零网络请求，可以下载到本地离线使用**。

## 覆盖的数据表

| 类型 | 条目数 | 说明 |
| --- | --- | --- |
| `buff` | 114 | Buff 数据库 |
| `buff_template` | 9181 | Buff 模板（机制底层逻辑） |
| `global_buff` | 985 | GlobalBuff |
| `rogue_item` | 3030 | 肉鸽藏品/分队/招募券…，按 6 个季度二级筛选 |
| `autochess` | 681 | 卫戍协议：干员棋子 / 策略 / 盟约 / 装备… |
| `recal_rune` | 131 | 全息作战矩阵，按关卡二级筛选 |
| **合计** | **14122** | 与上游桌面端 `show_hidden=false` 的可见条目一致 |

隐藏条目（`obj.hidden`，如「盒内的钱」「应急干员」）按上游桌面端的默认行为跳过；
需要时把上游的 `show_hidden` 打开后再导出即可。

## 手机端功能

- 搜索：空格分词、多词同时命中，列表用 `<mark>` 高亮
- 类型筛选 + 二级筛选（肉鸽季度 / 卫戍协议分类 / 全息关卡），每项带条数
- 详情页三个标签：**译文** / **原文**（格式化 JSON）/ **属性**（名称、ID、类型、分类、子类）
- 译文按上游 `document_model.document_rows` 的规则渲染：可折叠树、旁注（description）、
  `last_one` 节点不输出条件文本、条件分支单独成行
- 正文里的交叉引用（`<Buff|key>` 之类）渲染成可点击标签，点了直接在应用内跳转；
  解析不到目标的引用降级成纯文本，不会出现死链
- 详情页工具条：全展开 / 全折叠 / 换行 / 字号 13–20px
- 首页「最近浏览」（本地存 20 条，可清空）
- 深链：支持 `?target=Buff.sluggish[inf]`（与上游桌面端分享链接同格式）和 `#buff:sluggish[inf]`，
  可以分享、可以刷新还原；目标不存在时安全退回列表
- 主题：跟随系统 / 浅色 / 深色，选择记在 `localStorage`
- 导航：列表 → 条目 → 交叉引用可以多级深入，「回退」逐层返回并恢复各自的滚动位置

## 上游版本策略

```python
UPSTREAM_PIN = "32c915735442fc375f473329cad446d719ccedeb"   # build.py
```

这个构建是无人值守、定时自动跑的，而且会直接 import 上游代码在构建机上执行，
产物每天自动发布到 GitHub Pages，上游的任何改动都会直达用户浏览器。
所以**上游不跟着 `main` 走**：默认锁定到人工审过的 commit，升级时看 diff → 改这一行 → 提交。

需要注意的是，上游从 `9e5e879`（2026-10-29）之后**全部是未签名提交**，
那条 PGP 签名链到此为止。锁 SHA 的意义因此更大。

要临时跟随最新，用 `workflow_dispatch` 手动跑并在 `upstream_ref` 里填 `main`；
勾选 `lock_ref` 则会把本次实际用的 SHA 写回 `build.py`。

## 本地构建

```bash
python build.py -o dist/index.html
```

- 默认联网同步锁定的上游源码到 `.src/`（保留 `.src/tables` 里的游戏数据，不重复下载）
- 游戏数据缺哪个补哪个，来源是 [Kengxxiao/ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData)；
  `activity_table.json`（卫戍协议）与 `crisis_v2_table.json`（全息作战矩阵）是可选的，
  缺了只跳过那两张表，不让整次构建失败
- `--update-data` 强制重下全部数据表；`--no-update` 只用现有 `.src`；`--limit N` 每类只导 N 条（调试）

产物约 5 MB（14122 条，gzip 后数据包约 3.7 MB）。

## AI 补译（暂时关闭）

详情页原有的「AI」抽屉（片段补译、问答）因安全与使用效果考虑**暂时下线**：
构建出的页面不再包含任何 AI 入口与设置面板，也不会发起任何外部网络请求（CSP 已收紧为 `connect-src 'none'`）。
对应代码已从 `template.html` 移除；日后如需恢复，`git revert` 移除 AI 功能的那个提交即可。

## 数据来源与声明

- 翻译规则与词典：[@TeamTorappu/BenaProtractor](https://github.com/TeamTorappu/BenaProtractor)
- 游戏原始数据：[Kengxxiao/ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData)

本项目只是把上游的翻译结果做了移动端适配与预计算，**翻译规则完全来自 BenaProtractor**，未做任何业务逻辑改动。

沿用上游的声明：《贝娜的量角器》为分析工具与翻译工具，旨在为普通玩家提供阅读机制和算法的渠道，
其中不包含也没有任何计划包含编辑功能，亦不支持任何与「私服」相关的项目。我们坚决反对一切私服行为。
页面中出现的数值大多为默认数据，详细数据可能受给定黑板的制约。
