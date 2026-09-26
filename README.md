# 《贝娜的量角器》手机版

把 [TeamTorappu/BenaProtractor](https://github.com/TeamTorappu/BenaProtractor) 的翻译结果预先算好，
打包成一个自包含的 HTML 文件，手机浏览器直接打开就能检索、阅读。

- **译文 + 原文** 两个页签，和桌面版一致
- **完全离线可用**：数据以 gzip 内联在 HTML 里，打开即用，不发任何请求
- **跟随上游更新**：GitHub Actions 每天自动拉取上游最新规则与游戏数据，重新构建并发布

打开 Pages 地址就是最新的版本，无需手动下载任何文件。

## 首次部署

> **必须先做这一步**：仓库 → **Settings → Pages** → 把 **Source** 改成 **「GitHub Actions」**。
> 不先开启的话，构建能成功，但最后发布那一步会报
> `HttpError: Resource not accessible by integration`——因为仓库自带的 GITHUB_TOKEN
> 没有创建 Pages 站点的权限，工作流无法替你开启它。

1. 在 GitHub 新建一个仓库，选 **Public**（Actions 对公开仓库免费且不限时长）
2. **Settings → Pages → Source 选「GitHub Actions」**
3. 把本目录推上去：

   ```bash
   git remote add origin https://github.com/<你的用户名>/<仓库名>.git
   git push -u origin <当前分支>
   ```

4. 推送会自动触发构建；也可以到 **Actions** 页手动点 **Run workflow**
5. 访问 `https://<你的用户名>.github.io/<仓库名>/` —— 这就是手机版地址

之后每天北京时间凌晨 4 点自动重建，任何推送也会立即重建。构建产物同时作为 Actions 附件保留，
需要离线文件时可以在对应的运行记录里下载。

## 工作原理

手机浏览器里没有 Python，跑不了上游那套翻译规则。所以这里把「跑规则」放在 GitHub Actions 上：

```
Actions 定时 → 拉上游 Python 规则 + 鹰角游戏数据 → 在云端跑一遍翻译引擎
            → 产出 gzip 数据包 → 内联进 HTML → 发布到 GitHub Pages
```

手机端只负责解压、检索和渲染，不做任何翻译计算。

## 本地构建

```bash
python build.py --tables ../tables -o ../贝娜的量角器.html
```

| 参数 | 说明 |
| --- | --- |
| `--tables DIR` | 复用已有的游戏数据目录，避免重复下载 72 MB |
| `--no-update` | 不联网更新上游源码，只用现有 `.src` |
| `--update-data` | 强制重新下载游戏数据 |
| `--seasons 5,6` | 只打包指定肉鸽季度，可显著减小体积 |
| `--workdir` | 中间产物存放目录，默认脚本所在目录 |

只依赖 Python 标准库，无需安装任何第三方包。

## 数据来源与声明

- 翻译规则与词典：[@TeamTorappu/BenaProtractor](https://github.com/TeamTorappu/BenaProtractor)
- 游戏原始数据：[Kengxxiao/ArknightsGameData](https://github.com/Kengxxiao/ArknightsGameData)

本项目只是把上游的翻译结果做了移动端适配与预计算，**翻译规则完全来自上游**，未做任何业务逻辑改动。
上游缺陷一律以构建期补丁绕过（见 `compat.py`），不修改上游源码。

沿用上游的声明：《贝娜的量角器》为分析工具与翻译工具，旨在为普通玩家提供阅读机制和算法的渠道，
其中不包含也没有任何计划包含编辑功能，亦不支持任何与「私服」相关的项目。我们坚决反对一切私服行为。
页面中出现的数值大多为默认数据，详细数据可能受给定黑板的制约。
