# Daily Medical-AI Research Paper Digest Bot

这是一个“医学影像 AI 每日论文雷达”MVP：每天自动检索 **PubMed + arXiv + Semantic Scholar**，按主题和顶刊顶会加权打分，去重后发送邮件摘要。

默认研究方向：

- Medical imaging + AI
- Brain / neuroimaging 优先
- Brain-gut axis / gut-brain axis / microbiome + neuroimage
- Multi-organ guided diagnosis
- Alzheimer's disease diagnosis
- Medical image synthesis / enhancement
- Brain MRI / fMRI / PET / dementia / MCI / neurodegenerative disease
- 顶刊顶会加权：Nature / Science / Cell / Lancet 正刊与医学、神经、数字健康相关子刊，MICCAI、MIDL、ISBI、IEEE TMI、Medical Image Analysis、Radiology、NeurIPS、CVPR 等

## 文件说明

```text
paper_bot.py
config.yaml
requirements.txt
.env.example
README.md
.github/workflows/daily-paper-digest.yml
data/sent_papers.json   # 自动生成，用于避免重复发送
```

## 你的默认收件邮箱

本包已把默认收件人写为：

```text
dlmu.p.l.zhu@gmail.com
```

GitHub Secrets 里的 `MAIL_TO` 会覆盖配置文件；如果你不想在 secrets 里重复填，也可以保留 `config.yaml` 的 `email.to`。

## 核心设计

### 1. 为什么用 14 天窗口？

每日任务容易遇到数据库索引延迟。脚本用 `lookback_days: 14` 检索最近 14 天，然后用 `data/sent_papers.json` 去重，这样可以减少漏掉新文章的概率。

### 2. 为什么加 PubMed？

医学方向只靠 arXiv 会漏掉大量临床/放射/神经影像文章。PubMed 用 NCBI E-utilities 检索，适合抓正式发表论文；arXiv 抓预印本；Semantic Scholar 补 venue、引用和 TLDR。

### 3. “Nature / Science / Cell / Lancet 正刊和子刊”怎么抓？

新版有两层：

1. **PubMed 顶刊家族检索**：在 PubMed 查询里加入 Nature、Science、Cell、Lancet 正刊与相关子刊的 `[Journal]` 限定，再叠加 brain/neuroimaging/AI/Alzheimer/gut-brain 等主题词。
2. **Crossref 顶刊 DOI 元数据检索**：按 journal title + 主题词 + 最近日期窗口查 Crossref，补足 PubMed 索引延迟或非医学数据库中的新 DOI 记录。

### 4. “顶刊顶会”怎么识别？

在 `config.yaml` 的 `top_venue_boosts` 里做 pattern 匹配。命中 Nature、Science、Cell、Lancet 家族，Medical Image Analysis、IEEE TMI、Radiology、MICCAI、MIDL、ISBI、NeurIPS、CVPR 等，会额外加分。这个不是绝对过滤，因为很多新预印本还没有 venue。

## 本地测试

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# 编辑 .env，填入 SMTP 信息

# 只打印，不发邮件
DRY_RUN=true python paper_bot.py --config config.yaml --dry-run
```

正式发送：

```bash
export SMTP_HOST=smtp.gmail.com
export SMTP_PORT=587
export SMTP_USER=your_email@gmail.com
export SMTP_PASSWORD=your_16_digit_app_password
export MAIL_FROM=your_email@gmail.com
export MAIL_TO=dlmu.p.l.zhu@gmail.com
export NCBI_EMAIL
CROSSREF_MAILTO=dlmu.p.l.zhu@gmail.com
CROSSREF_MAILTO=dlmu.p.l.zhu@gmail.com

python paper_bot.py --config config.yaml
```

## GitHub Actions 部署

1. 新建一个私有 GitHub 仓库，例如 `medical-ai-paper-digest`
2. 把本压缩包内容上传到仓库根目录
3. 进入 `Settings` → `Secrets and variables` → `Actions` → `New repository secret`
4. 添加必要 secrets：

```text
SMTP_HOST
SMTP_PORT
SMTP_USER
SMTP_PASSWORD
MAIL_FROM
MAIL_TO
```

5. 建议添加：

```text
NCBI_EMAIL
CROSSREF_MAILTO
```

6. 可选添加：

```text
NCBI_API_KEY
S2_API_KEY
OPENAI_API_KEY
OPENAI_MODEL
```

7. 到 `Actions` 页面打开 `Daily Medical-AI Paper Digest`，点 `Run workflow` 手动跑一次。
8. 没问题后，它会每天新加坡时间约 07:15 自动运行。

## 调参建议

收到太少：

```yaml
scoring:
  min_score: 7
```

收到太多无关：

```yaml
scoring:
  min_score: 10
  exclude_keywords:
    - "某个噪音方向"
```

希望更偏脑/神经影像：

```yaml
scoring:
  soft_must_have_penalty: 5
```

希望不要漏掉 multi-organ：

```yaml
scoring:
  soft_must_have_penalty: 1
```

希望更看重顶刊顶会：

```yaml
scoring:
  top_venue_boosts:
    "Medical Image Analysis": 10
    "IEEE Transactions on Medical Imaging": 10
    "MICCAI": 10
```

## 邮件摘要风格

如果设置了 `OPENAI_API_KEY` 和 `OPENAI_MODEL`，邮件会让模型按如下结构总结：

- 属于哪类主题
- 数据/模态
- 方法
- 核心结论
- 为什么值得读/是否像顶刊顶会候选

不设置 OpenAI 也能跑，只是邮件会直接使用论文摘要或 Semantic Scholar TLDR。
