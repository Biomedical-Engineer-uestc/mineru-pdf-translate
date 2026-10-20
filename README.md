# pdf-translate

**用 MinerU 把英文 PDF 论文翻译成中文 PDF —— 模型全程不看图，token 省 2–3 倍。**

一个面向 AI Agent 的技能（也可以完全手动跑脚本）：把一篇英文论文变成排版端正的中文 PDF，公式、图片、表格原位保留，参考文献不浪费算力。

## 这是什么

把 PDF 直接丢给大模型翻译有两个问题：一是图片要花大量 token（一页里的图往往比整页文字还贵），二是模型看到图会忍不住"解读"图里内容，容易和正文混在一起。

这个项目把两件事拆开：**模型只翻译文字，脚本负责图片和排版**。

效果对比（同一篇 13 页论文）：

| 做法 | 输入 token | 结果 |
|---|---|---|
| 整份 PDF 直接翻译 | 3 万+（图片占大头） | 慢，图表内容可能被模型编造 |
| 本项目 | 约 1.2 万（纯文字） | 快，模型完全没看过图 |

## 功能

- **文字与图片分离**：图片、公式、表格转成 `[[FIG:001]]` 这类占位符，模型只处理文字
- **参考文献自动跳过**：占全文约 1/3 的参考文献不翻译，原样保留，省 34% token
- **逐块质量校验**：检查占位符数量/顺序、公式数量、标题数、段落数、中英比例，不合格就重译
- **学术排版**：宋体正文 + Times New Roman、黑体标题、首行缩进、标题作者居中、自动补「摘要」标题
- **解析档位可选**：`flash` / `basic`（默认，最快）/ `standard` / `advanced`
- **公式正确渲染**：LaTeX 公式经 MathML 输出，编号保留
- **可断点续传**：翻译中断后，已完成的块不会重做

## 适用场景

适合：

- 英文期刊论文、预印本，电子版（有文字层）PDF
- 想快速读懂内容，不要求复刻原版式
- 用 API 按 token 计费，希望压低成本
- 让 Agent 直接读文献，而不是只读出 PDF 里的纯文本

不适合：

- 需要保留原始双栏版式、页眉页脚、DOI 行 —— 输出是重新排版的新文档
- 需要翻译图里的文字（坐标轴、图例）—— 图内英文保持原样
- 扫描质量很差的影印件 —— 成稿质量取决于 MinerU 的识别效果
- 目标语言不是中文 —— 排版模板是中文向的

## 工作原理

```
PDF
 ├─ MinerU 解析 ──→ markdown.md + images/（图片是独立文件）
 ├─ 预处理 ───────→ 图片/公式/表格 变占位符；参考文献单独切出；按章节切块
 ├─ LLM 分块翻译 ──→ 只看到文字和占位符，一个图片 token 都不花
 ├─ 校验 ─────────→ 占位符、公式、标题、段落数、中英比例
 └─ 脚本回填 ─────→ 占位符换回真实内容 → pandoc 转 HTML → 浏览器打印 PDF
```

三点设计取舍：

1. **不让模型碰图片**。占位符由脚本回填，模型既不用看图，也没机会改图。
2. **不让模型排版**。模型只产出 markdown，PDF 由 pandoc + Edge 无头打印生成，避免模型"自由发挥"。
3. **用 HTML 而不是 LaTeX**。不依赖 TeX 发行版，换台机器不会因为缺宏包跑不起来。

## 安装

需要 Windows 10/11，以及 Edge 或 Chrome（系统一般自带）。

1. 把本仓库放到技能目录：

   ```text
   %USERPROFILE%\.agents\skills\pdf-translate\
   ```

   或者随便放一个目录，手动跑脚本也可以。

2. 双击 `setup.bat`（或在终端运行 `powershell -ExecutionPolicy Bypass -File setup.ps1`）。

安装脚本会自动完成：

- 下载 uv 与 CPython 3.12（无需预装 Python）
- 用仓库内置的 `vendor/mineru-4.0.12-py3-none-any.whl` 安装 MinerU
- 下载 pandoc 3.12.1
- 生成 `config.json` 记录各工具路径

总下载约 800 MB，装完约 900 MB。**模型权重（约 2 GB）不在安装包内**，首次解析时自动下载。

> 完全离线部署可以预先准备 wheelhouse 和模型目录，见 `config.json` 的路径配置。

## 使用

### 让 Agent 来做（推荐）

装好后直接对 Agent 说：

> 把 `D:\papers\xxx.pdf` 翻译成中文

技能会自动触发，依次完成解析 → 翻译 → 校验 → 出 PDF。报告里会说明成稿位置和已知差异。

### 手动跑

```bash
# 1. 解析 + 分块（默认 basic 档，最快）
python scripts/prepare.py "论文.pdf"

# 2. 逐块翻译，写入 论文_translate/translated/chunk_00.md …
#    按 manifest.json 的块列表依次处理

# 3. 校验
python scripts/check.py "论文_translate"

# 4. 生成 PDF
python scripts/build.py "论文_translate"
```

产物在 `论文_translate/final/`：`论文.zh.md`、`论文.zh.html`、`论文.zh.pdf`。

### 换解析档位

```bash
python scripts/prepare.py "论文.pdf" --tier standard   # 复杂版面/扫描件
python scripts/prepare.py "论文.pdf" --pages 1-5       # 先试几页
```

| 档位 | 特点 |
|---|---|
| `flash` | 纯 CPU，最快，质量最低，适合预览 |
| `basic` | 默认。ONNX 模型，CPU 运行，质量与速度平衡 |
| `standard` | 调用 VLM，复杂版式质量更好，需要显存 |
| `advanced` | 最高质量，最慢 |

## 目录结构

```text
pdf-translate/
├── SKILL.md              技能说明（Agent 读取）
├── README.md
├── setup.bat             一键安装入口
├── setup.ps1             安装逻辑
├── config.example.json   手动配置示例
├── vendor/
│   └── mineru-4.0.12-py3-none-any.whl
└── scripts/
    ├── prepare.py        MinerU 解析、占位符化、分块
    ├── check.py          译文校验
    ├── build.py          回填、排版、生成 PDF
    └── config.py         工具路径发现
```

## 常见问题

**首次解析特别慢？** 在下载 2 GB 模型，第二次就正常了。

**报 `parse_oom` 或显存不足？** 用 `--tier basic`，它走 CPU，不吃显存。

**没有 Edge 怎么办？** Chrome 也可以，`config.json` 里指向 `chrome.exe` 即可。

**PDF 生成失败？** 打开 `final/*.zh.html`，Ctrl+P 手动打印成 PDF，效果一样。

**译文有漏翻或错位？** `check.py` 会用占位符和段落数把问题块标出来，重译那几块再跑一次。

**能翻译其他语言吗？** 可以改翻译规则里的目标语言，但排版（宋体、摘要标题）是为中文准备的。

## 致谢

本项目建立在 [MinerU](https://github.com/opendatalab/MinerU) 之上。**MinerU 是整个流程的基石**——PDF 版面分析、OCR、公式识别、图片抽取全部由它完成。它来自 [OpenDataLab](https://opendatalab.com/)（上海人工智能实验室）团队，识别质量和对复杂学术版面的处理能力，是这个想法能成立的前提。感谢 MinerU 团队的开源工作。

其他依赖：

- [pandoc](https://pandoc.org/) — markdown 转 HTML
- Microsoft Edge / Google Chrome — HTML 打印为 PDF
- [uv](https://github.com/astral-sh/uv) — Python 环境管理

## License

本项目代码采用 MIT License，见 [LICENSE](LICENSE)。

MinerU 采用 Apache License 2.0（附带商业使用条款），其许可证全文随仓库内 wheel 一并分发，详见 [NOTICE](NOTICE)。
