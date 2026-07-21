# Medical Imaging Deep Learning Paper Radar

This repository publishes a daily GitHub Pages dashboard for recent deep-learning papers relevant to Pengli Zhu's medical image analysis research.

Live site: https://idea89560041.github.io/Paper-Radar/

The radar searches PubMed, arXiv preprints, Semantic Scholar, and Crossref metadata, then scores papers against the research profile in `config.yaml`. It focuses on neuroimaging, brain MRI/PET, BCI, EEG, agentic AI for medical imaging, whole-body PET/MRI, multi-organ diagnosis, Alzheimer disease, brain-gut / microbiome neuroimaging, foundation models, vision-language models, generative AI, and medical image synthesis.

The web page groups results into flagship main journals, flagship-family subjournals, top medical-imaging / AI venues, preprints, and other relevant journals. Traditional neuroscience-only papers and low-priority venues such as Scientific Reports or Frontiers journals are filtered out.

The GitHub Actions workflow updates the site every day at about 16:10 China/Hong Kong/Singapore time, and also redeploys when local reading notes are pushed.

## Local Reading Notes

PDFs added to this local folder can be turned into a separate reading-notes column on the site:

`D:\OneDrive - The Chinese University of Hong Kong\Paper_Radar`

GitHub Actions cannot read that local OneDrive folder directly, so the local Windows task scans the folder on this computer, detects new PDFs by file hash, extracts the abstract, Introduction excerpt, main figure/caption when possible, commits only generated JSON/image assets, and pushes them to GitHub. The PDFs themselves are not committed.

Install dependencies in the local `pet` environment:

```powershell
D:\Users\plzhu\anaconda3\envs\pet\python.exe -m pip install -r requirements.txt
```

Publish new local readings once:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\update_local_readings.ps1
```

Install the daily local scanner:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_local_readings_task.ps1 -Time 16:35
```

Abstracts and figure captions are translated with free offline Argos Translate by default. `OPENAI_API_KEY` and `OPENAI_MODEL` are optional; when present, they are used only for richer interpretation of Introduction logic, innovation points, and method notes. You can also set `TRANSLATION_PROVIDER=libretranslate` plus `LIBRETRANSLATE_URL` if you prefer a LibreTranslate-compatible API, but that sends extracted text to the selected translation service.
