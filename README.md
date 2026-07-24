
# VAST Challenge 2026 · MC1

本目录是对原工作压缩包的**结构化副本**。原始压缩包及其中的文件没有被修改；现有文件仅被复制、重命名路径和重新分类。重复图片与 `.DS_Store` 没有放入本副本，详细映射见：

- `docs/reorganization_manifest.csv`
- `docs/file_integrity_sha256.csv`

## 1. 项目目标

本项目分析 TenantThread 在 Project HarborCrest 并购信息禁令解除前发生的社交媒体泄露，重点回答：

1. 哪些事件、角色、决策和系统缺口导致了提前发布？
2. 导致泄露的行为与各代理的历史典型行为有何不同？
3. 泄露前是否存在可识别的先行指标，为什么先前异常没有触发明显纠正？

核心调查判断不是简单区分“故意泄露”或“系统故障”，而是识别**有意识的提前发布行为如何借助组织控制失效而成为可能**。

## 2. 当前完成状态

| 模块 | 状态 | 现有内容 |
|---|---|---|
| 原始数据与数据说明 | 已整理 | `data/raw/`、`docs/reference/` |
| 数据清洗 | 已完成 | 清洗脚本及 `data/cleaned/` |
| 特征工程 | 已完成 | 特征脚本及 `data/features/` |
| 第一问 | 基本完成 | 中英文答案、讲解稿、4 组图形文件 |
| 第二问 | 部分完成 | 已有 Behavior DNA 图，正式答案仍待补充 |
| 第三问 | 数据已准备 | 已有先行指标与偏离度数据，图形和正式答案仍待完成 |
| 最终网页提交 | 未完成 | 官方模板已保留在 `submission/template/` |
| 展示视频 | 未完成 | 后续应与最终网页一起准备 |

## 3. 目录结构

```text
VAST_MC1_organized/
├── README.md
├── requirements.txt
├── .gitignore
├── data/
│   ├── raw/                 # 只读原始数据
│   ├── cleaned/             # 清洗后的标准化数据
│   └── features/            # 消息、关系、偏离度和先行指标特征
├── src/
│   ├── data/                # 数据清洗代码
│   ├── features/            # 特征工程代码
│   ├── visualization/       # 后续所有绘图脚本应放在这里
│   └── utils/               # 后续共享函数和常量
├── analysis/
│   ├── q1/                  # 第一问文字材料
│   ├── q2/                  # 第二问当前状态与后续答案
│   ├── q3/                  # 第三问当前状态与后续答案
│   └── evidence_index_template.csv
├── outputs/
│   ├── figures/
│   │   ├── q1/
│   │   ├── q2/
│   │   └── q3/
│   └── reports/
├── docs/
│   ├── reference/
│   ├── reorganization_manifest.csv
│   ├── file_integrity_sha256.csv
│   └── validation_report.txt
└── submission/
    ├── template/
    ├── assets/
    └── README.md
```

## 4. 快速开始

推荐使用 Python 3.9 或更高版本。

```bash
python -m venv .venv
```

Windows PowerShell：

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

macOS / Linux：

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### 重新生成清洗数据

```bash
python src/data/clean_data.py \
  --input data/raw/MC1_final_00.json \
  --outdir data/cleaned
```

Windows PowerShell 也可以写成一行：

```powershell
python src/data/clean_data.py --input data/raw/MC1_final_00.json --outdir data/cleaned
```

### 重新生成特征数据

```bash
python src/features/extract_features.py \
  --indir data/cleaned \
  --outdir data/features
```

已有的 CSV 和 JSON 输出已经包含在压缩包中，因此只查看成果时不必重新运行。

> `clean_data.py` 是原来的 `clean_data(1).py` 的路径重命名副本，代码内容没有修改。脚本注释中可能仍出现旧文件名。

## 5. 关键数据文件

### `data/cleaned/`

- `messages_clean.csv`：每行一条消息，含时间、代理、渠道、正文、内部状态和回复关系。
- `environment_clean.csv`：每行一个 round，含舆情、新闻、市场和代理可用性。
- `participants_clean.csv`：每行一个 round-agent 组合。
- `agents_dim.csv`：7 个代理的统一角色维度。
- `mc1_clean.json`：便于 JavaScript / D3 使用的整合数据。

### `data/features/`

- `messages_features.csv`：并购敏感、规避、合理化、角色外行为和泄露风险等消息级特征。
- `message_edges.csv`：可信回复、重建线程和 @提及关系。
- `agent_round_fingerprint.csv`：完整的 Agent × Round 行为指纹。
- `behavior_deviation.csv`：相对危机前基线的行为偏离度。
- `leading_indicators.csv`：按 round 汇总的先行指标。
- `environment_text_features.csv`：环境叙事和新闻文本特征。

## 6. 分析材料与图形

### 第一问

文字材料位于 `analysis/q1/`，图形位于 `outputs/figures/q1/`：

- `q1_timeline_cn.png/.svg`
- `q1_timeline_en.png/.svg`
- `q1_actor_sequence_en.png`
- `q1_control_bypass_en.png`

### 第二问

现有图：

- `outputs/figures/q2/q2_behavior_dna_en.png`

仍需补充：

- `analysis/q2/answer_cn.md`
- `analysis/q2/answer_en.md`
- 一张覆盖全部 7 个代理的行为偏离总览图
- 对 Legal、Social Media 和 Judge 之外角色的说明

### 第三问

可直接使用的数据：

- `data/features/leading_indicators.csv`
- `data/features/behavior_deviation.csv`
- `data/features/messages_features.csv`

建议后续生成：

- `outputs/figures/q3/q3_leading_indicators_en.png`
- `outputs/figures/q3/q3_expected_vs_actual_en.png`
- 一张解释“为什么先前异常没有触发纠正”的控制失效图

## 7. 新增图形和代码时的规则

1. 绘图代码统一放在 `src/visualization/`。
2. 生成图片统一放在 `outputs/figures/q1/`、`q2/` 或 `q3/`。
3. 不再使用 `visual_picture/` 或 `1_1.png`、`2_1.png` 这类无语义文件名。
4. 文件名使用小写英文、下划线和语言后缀，例如：

```text
q3_leading_indicators_en.png
q3_leading_indicators_cn.png
```

5. 原始数据 `data/raw/MC1_final_00.json` 应视为只读。
6. 每个正式结论都应能追溯到具体消息。可从 `analysis/evidence_index_template.csv` 复制模板，为 Q1、Q2 和 Q3 分别建立证据索引。

## 8. 最终提交

官方 Answer Sheet 原件位于：

```text
submission/template/original_answer_sheet.htm
```

完成三道题后：

1. 复制模板并生成 `submission/index.htm`。
2. 将提交所需图片放入 `submission/assets/images/`。
3. 将交互数据放入 `submission/assets/data/`。
4. 将 CSS 和 JavaScript 分别放入对应目录。
5. 检查网页在离线状态下能否完整打开。
6. 准备展示如何使用可视分析形成结论的视频。

当前压缩包**没有伪造一个未完成的 `index.htm`**，以免与最终提交版本混淆。

## 9. 完整性说明

- 源压缩包未被覆盖、改名或删除。
- 迁移后的源文件按 SHA-256 进行了校验。
- `visual_picture/1_1.png`、`1_2.png`、`1_3.png` 是 Q1 图片的精确重复副本，因此只保留语义清晰的正式文件名。
- `.DS_Store` 属于系统元数据，已排除。
- 所有迁移、重命名和省略记录均可在 `docs/reorganization_manifest.csv` 中查看。
