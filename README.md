# 《贝娜的量角器》手机版

把 [TeamTorappu/BenaProtractor](https://github.com/TeamTorappu/BenaProtractor) 的翻译结果预先算好，
打包成一个自包含的 HTML 文件，手机浏览器直接打开就能检索、阅读。

## 工作原理

手机浏览器里没有 Python，跑不了上游那套翻译规则。所以这里把「跑规则」放在 GitHub Actions 上：

```
Actions 定时 → 拉上游 Python 规则 + 鹰角游戏数据 → 在云端跑一遍翻译引擎
            → 产出 gzip 数据包 → 内联进 HTML → 发布到 GitHub Pages
```

手机端只负责解压、检索和渲染，不做任何翻译计算。

## AI 补译（可选）

详情页顶部的「AI」抽屉对应桌面版的 AI 侧栏，用来补齐引擎没翻出来的片段，也能就当前条目提问：

- **片段补译**：列出条目里所有 `（未翻译）`／`（翻译失败）` 的片段，逐条或点「全部翻译」批量调用 AI，
  结果写回译文树，显示成 `中文译名（原标识）`
- **问答**：就当前条目提问，回答流式输出

在抽屉「设置」里填 OpenAI 兼容接口（DeepSeek / 硅基流动 / Ollama / LM Studio…）的 `base_url`、模型名与 API Key 即可，
也可把桌面版 `.bena_ai.json` 整段粘进「粘贴配置 JSON」导入。**API Key 只存在本标签页的会话存储（sessionStorage）里**：
刷新不用重填，关闭标签页后自动清除，不写入长期本地存储，也不写进 HTML。接口地址强制 `https://`
（本机模型可用 `http://localhost` / `http://127.0.0.1`），避免 Key 明文传输。
翻译结果缓存在浏览器本地，可「导出缓存」成 Markdown，不会修改任何词典文件。

不配置就一直完全离线，只有点「翻译」或「问」时才联网。接口需放行 CORS 才能被浏览器直接调用。

## 数据来源与声明

- 翻译规则与词典：[@TeamTorappu/BenaProtractor](https://github.com/TeamTorappu/BenaProtractor)
- 游戏原始数据：[Kengxxiao/ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData)

本项目只是把上游的翻译结果做了移动端适配与预计算，**翻译规则完全来自上游**，未做任何业务逻辑改动。
上游缺陷一律以构建期补丁绕过（见 `compat.py`），不修改上游源码。

沿用上游的声明：《贝娜的量角器》为分析工具与翻译工具，旨在为普通玩家提供阅读机制和算法的渠道，
其中不包含也没有任何计划包含编辑功能，亦不支持任何与「私服」相关的项目。我们坚决反对一切私服行为。
页面中出现的数值大多为默认数据，详细数据可能受给定黑板的制约。