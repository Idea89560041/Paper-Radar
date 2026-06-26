# Medical Imaging AI Paper Radar

这是一个每天自动更新的 Medical Imaging AI 论文雷达网页。它会检索 PubMed、arXiv、Semantic Scholar 和 Crossref 顶刊来源，按 `config.yaml` 里的研究方向打分，然后部署到 GitHub Pages。

默认现在不再发送邮件，因此不需要 SMTP Secret。

## 网页地址

启用 GitHub Pages 后，网页通常在：

```text
https://idea89560041.github.io/Paper-Radar/
```

页面会显示标题、来源、期刊/会议、日期、作者、摘要、链接、匹配原因和 score。机器可读数据在同目录的 `papers.json`。

## 研究方向

重点方向保留在 `config.yaml`：

- medical imaging + AI
- brain / neuroimage / neuroimaging
- brain-gut axis / gut-brain axis
- microbiome + neuroimaging
- multi-organ guided diagnosis
- Alzheimer disease diagnosis
- dementia / MCI / MRI / fMRI / PET / amyloid / tau
- medical image synthesis / enhancement
- diffusion model / generative AI / super-resolution / denoising
- foundation model / vision-language model / large multimodal model for radiology or neuroimaging

默认 `lookback_days: 14`，默认 `scoring.min_score: 8`。论文太少可以把 `min_score` 调到 7；噪音太多可以调到 9 或 10。

## 数据源

- PubMed / NCBI E-utilities：医学、生物医学和神经影像方向。
- arXiv API：AI、计算机视觉、医学图像生成和 foundation model 预印本。
- Semantic Scholar Graph API：补充 citation、venue、TLDR 和跨学科论文。
- Crossref REST API：按 Nature、Science、Cell、Lancet、Medical Image Analysis、IEEE TMI、Radiology 等来源抓 DOI 元数据。

## 顶刊顶会

配置保留并加权以下来源：

- Nature、Nature Medicine、Nature Neuroscience、Nature Biomedical Engineering、Nature Methods、Nature Communications、Communications Medicine、npj Digital Medicine
- Science、Science Translational Medicine、Science Advances
- Cell、Neuron、Cell Reports Medicine、Patterns
- The Lancet、The Lancet Digital Health、The Lancet Neurology、eBioMedicine、eClinicalMedicine
- Medical Image Analysis、IEEE Transactions on Medical Imaging、Radiology
- MICCAI、MIDL、ISBI、NeurIPS、ICLR、ICML、CVPR

## GitHub Actions

workflow 文件：

```text
.github/workflows/daily-paper-digest.yml
```

它会：

1. 每天中国/香港/新加坡时间约 16:10 自动运行。
2. 手动运行时也会立即刷新网页。
3. 执行 `python paper_bot.py --config config.yaml --web --output-dir site`。
4. 用 GitHub Pages 发布静态网页。

GitHub cron 使用 UTC，所以配置为：

```yaml
10 8 * * *
```

## GitHub Pages 设置

如果页面第一次打开是 404，到仓库：

`Settings` -> `Pages` -> `Build and deployment`

把 Source 设为 `GitHub Actions`。之后重新运行一次 workflow。

## Secrets

网页模式没有必填 Secret。

建议添加：

```text
NCBI_EMAIL=dlmu.p.l.zhu@gmail.com
CROSSREF_MAILTO=dlmu.p.l.zhu@gmail.com
```

可选添加：

```text
S2_API_KEY
NCBI_API_KEY
OPENAI_API_KEY
OPENAI_MODEL
```

说明：

- `S2_API_KEY` 可以减少 Semantic Scholar 429 限流。
- `NCBI_API_KEY` 可以提高 PubMed 请求额度。
- `OPENAI_API_KEY` 和 `OPENAI_MODEL` 只用于生成更好的中文摘要；不填也会使用原始摘要。

SMTP 相关 Secret 现在不再需要：

```text
SMTP_HOST
SMTP_PORT
SMTP_USER
SMTP_PASSWORD
MAIL_FROM
MAIL_TO
```

保留它们也没关系，新的网页 workflow 不会读取这些值。

## 手动刷新

进入仓库：

`Actions` -> `Daily Medical-AI Paper Radar Site` -> `Run workflow`

运行完成后打开 GitHub Pages 地址查看最新网页。

## 本地测试

Windows 可以用你的 conda 环境：

```powershell
D:\Users\plzhu\anaconda3\envs\pet\python.exe -m py_compile paper_bot.py
D:\Users\plzhu\anaconda3\envs\pet\python.exe paper_bot.py --config config.yaml --web --output-dir site
```

然后打开：

```text
site/index.html
```

## 常见问题

- 页面 404：检查 GitHub Pages Source 是否为 `GitHub Actions`，然后重新运行 workflow。
- workflow 没有按时出现：GitHub schedule 不是精确闹钟，可能延迟几分钟；手动 `Run workflow` 可以立即刷新。
- Semantic Scholar 429：添加 `S2_API_KEY`，或降低 query 数和频率。
- PubMed 限流：添加 `NCBI_EMAIL` 和 `NCBI_API_KEY`。
- Crossref 限流：添加 `CROSSREF_MAILTO`，必要时降低 `crossref_top_journals.max_calls`。
- 论文太少：降低 `scoring.min_score` 或增加 query。
- 噪音太多：提高 `scoring.min_score`，或增加 `exclude_keywords`。

不要把任何 API key、SMTP 密码、Google App Password、OpenAI key、NCBI key 或 Semantic Scholar key 写入代码、README、日志或普通文件。
