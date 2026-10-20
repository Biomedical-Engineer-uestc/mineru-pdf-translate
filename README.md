# pdf-translate

**用 MinerU 提取论文，翻译文字、保留图表，生成重新排版的中文 PDF —— 翻译阶段模型只读文字，不读图片。**

一个面向 AI Agent 的技能（也可以完全手动跑脚本）：把一篇英文论文变成排版端正的中文 PDF，公式、图片、表格按阅读顺序回填，参考文献不浪费算力。

## 这是什么

本项目将文字翻译和文档构建分开：模型翻译提取的文字，脚本保存并回填图片、公式和表格。翻译阶段无需读取图像，验收阶段仍需查看页面。实际成本和耗时取决于论文、解析方式和核对范围，不保证固定的 token 节省比例。

自动校验检查结构、公式和部分漏译情况，不能保证 OCR 或语义准确。正式交付前还需核对原文与最终 PDF。

## 功能

- **文字与图片分离**：图片、公式、表格转成 `[[FIG:001]]` 这类占位符，模型只处理文字
- **参考文献按章节保留**：仅提取到下一个标题，以 REF 占位符回填原位置，其后的方法和附录继续翻译
- **逐块校验**：检查占位符数量/顺序、公式完整内容/顺序、标题数、段落数、中英比例及整段漏译；支持带理由的作者/机构原文保留清单
- **学术排版**：宋体正文 + Times New Roman、黑体标题、首行缩进、标题作者居中、自动补「摘要」标题
- **解析档位可选**：`flash` / `basic`（默认，最快）/ `standard` / `advanced`
- **公式渲染**：LaTeX 经 MathML 输出，编号转换后保留；仍需核对识别与渲染效果
- **可断点续传**：翻译中断后，已完成的块不会重做

## 实测数据

一篇 13 页英文论文（Brain Communications）的处理结果：

| 项 | 数值 |
|---|---|
| 交给模型的正文 | 50,791 字符 ≈ 12.7k tokens |
| 未进入上下文的参考文献 | 17,062 字符（约占原文 1/3） |
| 图片 / 公式 | 14 张图 + 3 个公式，压缩成 17 个占位符 |
| 分块 | 13 块，最大 5,904 字符 |
| 成稿 | 重新排版的中文 PDF，图表与公式按原位回填 |

和"把整份 PDF 或带 base64 图片的 markdown 直接交给模型"相比，模型不再读取图像内容，输入规模主要由正文决定。实际节省幅度取决于图表密度：图文混排的论文收益更大。

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
 ├─ LLM 分块翻译 ──→ 翻译阶段读取文字和占位符
 ├─ 校验 ─────────→ 占位符、公式内容、标题、段落数、逐段漏译
 └─ 脚本回填 ─────→ 占位符换回真实内容 → pandoc 转 HTML → 浏览器打印 PDF
```

三点设计取舍：

1. **翻译阶段保留图像**。占位符由脚本回填；验收时检查页面，避免把图像解读写入译文。
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

### 作为插件安装（可选）

本仓库同时可以打包成 ZCode 插件，从插件市场安装，而不是手动放技能目录：

```bash
python build_plugin.py --version 1.1.1
```

产物在 `dist/`：

```text
dist/
├── pdf-translate/            插件目录
├── pdf-translate-plugin.zip  可分发的插件包
└── marketplace.json          本地测试用市场清单
```

在应用里打开 **插件市场 → 添加 → 添加插件市场**，粘贴 `dist` 目录的绝对路径，即可在「Personal」下看到并安装。

安装后仍需在插件目录里运行一次 `setup.bat` 准备 MinerU 等依赖。

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

构建会重新校验，遇到缺译文、FAIL 或无法恢复的占位符会在写出前停止，不用英文原文补位。WARN 允许构建，但仍须核对。首页的作者行和编号机构行由 prepare 自动登记为原文保留，无需手动处理；脚注、通讯信息、关键词一般应当翻译，若决定保留英文再手动加入 `verbatim_paragraphs`（每项填写精确 `text` 和 `reason`），详见 SKILL.md。漏译检查是启发式规则，不能替代语义审阅。

更换输入文件、页码范围或解析档位时使用新的 `--work` 目录，避免复用旧解析。参考文献边界依赖 Markdown 标题，须对照原文核对；旧工作目录需重新准备才能修复此前误划入参考文献的正文。

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

**译文有漏翻或错位？** `check.py` 能发现部分结构和整段漏译问题，修复对应块后重跑。短句漏译、语义和位置仍需对照原文核对。

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

## 开发测试

```bash
python -B -X utf8 -m unittest discover -s tests -v
```

测试覆盖公式篡改、纯英文漏译、原文保留清单、参考文献后的正文、占位符回填和构建门槛，不依赖模型下载。

安装好 pandoc 和 Edge 后，可用新的工作目录执行实际 PDF 构建冒烟测试：

```bash
python -B -X utf8 tests/smoke_pdf.py "新的测试目录"
```

该测试使用合成的解析后文本，不测试 MinerU OCR。生成 PDF 后仍需渲染页面做视觉核对。
