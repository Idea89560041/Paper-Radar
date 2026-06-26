# Daily Medical-AI Research Paper Digest Bot

这是一个 Medical Imaging AI 每日论文邮件机器人。它每天自动检索 PubMed、arXiv、Semantic Scholar、Crossref 顶刊家族与专业期刊来源，按研究方向和顶刊顶会权重筛选新论文，然后把摘要发送到默认邮箱：

```text
dlmu.p.l.zhu@gmail.com
```

`MAIL_TO` 环境变量或 GitHub Secret 的优先级高于 `config.yaml`；如果没有设置 `MAIL_TO`，脚本会回退到 `config.yaml` 里的 `email.to`。

## 文件结构

```text
paper_bot.py
config.yaml
requirements.txt
.env.example
README.md
.github/workflows/daily-paper-digest.yml
data/.gitkeep
```

`data/sent_papers.json` 会在运行时自动创建，用于记录已成功发送的论文，避免重复推送。

## 数据源

- PubMed / NCBI E-utilities：正式医学与生命科学论文，适合抓取 neuroimaging、Alzheimer、MRI/PET、brain-gut axis 等医学主题。
- arXiv API：预印本，适合抓取 diffusion model、foundation model、vision-language model、super-resolution、denoising 等 AI 方法论文。
- Semantic Scholar Graph API：补充跨学科论文、venue、citation、TLDR 和 DOI 信息。
- Crossref REST API：按 Nature / Science / Cell / Lancet 家族及专业期刊检索 DOI 元数据，补足数据库索引延迟。

## 研究方向

重点方向在 `config.yaml` 中配置，包括：

- medical imaging + AI
- brain / neuroimage / neuroimaging
- brain-gut axis / gut-brain axis
- microbiome + neuroimaging
- multi-organ guided diagnosis
- Alzheimer’s disease diagnosis
- dementia / MCI / MRI / fMRI / PET / amyloid / tau
- medical image synthesis / enhancement
- diffusion model / generative AI / super-resolution / denoising
- foundation model / vision-language model / large multimodal model for radiology or neuroimaging

默认 `lookback_days: 14`，配合 `data/sent_papers.json` 去重，降低 PubMed、Semantic Scholar、Crossref 索引延迟造成的漏报概率。默认 `min_score: 8`；论文太少可以降到 7，噪音太多可以升到 10 或更高。

## 顶刊顶会来源

配置中保留并增强了以下来源或加权：

- Nature、Nature Medicine、Nature Neuroscience、Nature Biomedical Engineering、Nature Methods、Nature Communications、Communications Medicine、npj Digital Medicine
- Science、Science Translational Medicine、Science Advances
- Cell、Neuron、Cell Reports Medicine、Patterns
- The Lancet、The Lancet Digital Health、The Lancet Neurology、eBioMedicine、eClinicalMedicine
- Medical Image Analysis、IEEE Transactions on Medical Imaging、Radiology
- MICCAI、MIDL、ISBI、NeurIPS、ICLR、ICML、CVPR

## 本地测试

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m py_compile paper_bot.py
python paper_bot.py --config config.yaml --dry-run
```

`--dry-run` 只打印摘要，不发送邮件，也不会把论文标记为已发送。

## GitHub Actions 部署

1. 打开仓库的 `Settings` → `Secrets and variables` → `Actions`。
2. 添加必填 secrets：

```text
SMTP_HOST
SMTP_PORT
SMTP_USER
SMTP_PASSWORD
```

3. 建议添加：

```text
MAIL_TO=dlmu.p.l.zhu@gmail.com
MAIL_FROM
NCBI_EMAIL=dlmu.p.l.zhu@gmail.com
CROSSREF_MAILTO=dlmu.p.l.zhu@gmail.com
```

4. 可选添加：

```text
S2_API_KEY
NCBI_API_KEY
OPENAI_API_KEY
OPENAI_MODEL
```

5. 到 `Actions` → `Daily Medical-AI Paper Digest` → `Run workflow`。
6. 第一次手动运行保持 `dry_run=true`，确认日志里能抓到论文并生成摘要。
7. 确认无误后，再手动选择 `dry_run=false` 做真实发信。

工作流每天新加坡/香港时间约 07:15 自动运行。GitHub cron 使用 UTC，因此配置为：

```yaml
15 23 * * *
```

工作流使用 `permissions: contents: write`，真实发送成功后会自动提交 `data/sent_papers.json`。如果没有状态变化，commit 步骤会正常跳过。

## Gmail SMTP 示例

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=我的 Gmail
SMTP_PASSWORD=Google App Password，不是 Gmail 登录密码
MAIL_FROM=我的 Gmail
MAIL_TO=dlmu.p.l.zhu@gmail.com
```

不要把真实 SMTP 密码、Google App Password、OpenAI key、NCBI key 或 Semantic Scholar key 写入代码、README、日志或普通文件。请只放在 GitHub Secrets 或本地 `.env` 中；`.env` 已被 `.gitignore` 忽略。

## 常见错误处理

- SMTP 登录失败：检查 Gmail App Password、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_HOST`、`SMTP_PORT`。
- workflow 无法 push `data/sent_papers.json`：到仓库 `Settings` → `Actions` → `General` → `Workflow permissions`，开启 `Read and write permissions`。
- Semantic Scholar 限流：添加 `S2_API_KEY`，或降低 query 数、`max_results_per_query`、运行频率。
- PubMed 限流：添加 `NCBI_EMAIL` 和 `NCBI_API_KEY`。
- Crossref 限流：添加 `CROSSREF_MAILTO`，并降低 `crossref_top_journals.max_calls`。
- 没有论文：降低 `scoring.min_score`，增加 query，或暂时提高 `lookback_days`。
- 噪音太多：提高 `scoring.min_score`，增加 `exclude_keywords`，或提高 `soft_must_have_penalty`。

## 配置开关

四个来源都可以在 `config.yaml` 单独开启或关闭：

```yaml
sources:
  pubmed:
    enabled: true
  arxiv:
    enabled: true
  semantic_scholar:
    enabled: true
  crossref_top_journals:
    enabled: true
```
