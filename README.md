# FolderScout

Windows 桌面工具：选择磁盘 → 扫描文件夹 → 输入关键词 → 返回 TopN 最匹配的文件夹路径。

默认启用「规则粗筛 + 语义重排」混合匹配。

## 安装运行

```bash
pip install -r requirements.txt
python app.py
```

首次启动会自动下载 `BAAI/bge-small-zh-v1.5` 模型（约 92MB），后续走本地缓存。
若项目根目录已有 `models/`（见下节结构），则完全离线加载。

## 打包 exe

模型需要预置到项目根目录的 `models/`，打包时会被一并收进去，用户端无需联网。

**目录结构要求**：fastembed 走的是 HuggingFace 缓存布局，`models/` 必须是
`<cache_dir>/models--<org>--<repo>/snapshots/<revision>/<模型文件>` 的形式。
本项目使用 fastembed 的 ONNX 权重（`Qdrant/bge-small-zh-v1.5`）：

```
models/
└── models--Qdrant--bge-small-zh-v1.5/
    ├── refs/main                     # 内容就是一个 main，不能带换行
    └── snapshots/main/
        ├── model_optimized.onnx      # fastembed 只认这个文件名
        ├── config.json
        ├── tokenizer.json
        ├── vocab.txt
        └── ...（其余 tokenizer/config 文件）
```

> `refs/main` 必须存在且**不带尾随换行**：huggingface_hub 会把它当作快照目录名去拼路径。
> `model.safetensors` / `pytorch_model.bin` 在 ONNX 推理路径上用不到，无需打包。

构建：

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller FolderScout.spec --noconfirm
```

产物在 `dist/FolderScout/`，双击运行 `FolderScout.exe`。

说明：
- 已用 `collect_all` 收集 `fastembed` 和 `onnxruntime` 的依赖与动态库。
- 未启用 `--onefile`，启动快、杀软误报少。不要开 UPX。
- spec 里排除了用不到的 PySide6 子模块（WebEngine / Quick / QtPdf 等），瘦身明显。
- 若模型加载失败，程序会自动降级为纯规则匹配，不会崩溃。

## 匹配算法

1. **归一化**：分隔符（`_ - . ~ 空格` 等）统一，转小写。
2. **规则粗筛**：对 basename 和完整路径分别做「token AND + 去分隔符子串」双路打分，
   每个关键词取 basename/完整路径的较大值；任一词完全未命中即判为无关（0 分），
   否则按命中词的平均分排序。用 `heapq.nlargest` 取 TopK。
3. **语义重排**：对 TopK 候选用 bge-small-zh 做 embedding 余弦相似度重排，输出 TopN。
   启动时后台预热模型。

`TopN`（界面上「显示 N 条」）默认 **5**。

### 多盘扫描

磁盘以可点选的胶囊按钮展示，点一下即选中/取消，可同时勾选多个；点「全选」在
全选与全不选之间切换。各盘串行扫描后结果合并，统一做一次预处理，进度按累计数量显示。

### 搜索方式

输入关键词即自动搜索（300ms 防抖），无需按回车；双击结果直接用系统默认程序打开文件夹。

