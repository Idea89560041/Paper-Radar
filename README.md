# Brain / Neuroimage Medical AI Paper Radar

This repository powers a daily GitHub Pages dashboard for recent deep learning papers in brain image, neuroimage, and high-value medical imaging research.

The radar now prioritizes Brain image / Neuroimage papers, especially MRI, fMRI, PET, Aβ-PET / amyloid-beta PET, foundation models, vision-language models, and self-supervised learning. Alzheimer disease, dementia, MCI, Parkinson disease, brain tumors, stroke, epilepsy, and other brain-imaging applications remain high-priority topics. Whole-body PET/MRI and other organ medical imaging papers are included as secondary signals when they appear in strong venues.

The site is updated automatically every day at about 08:00 China/Hong Kong/Singapore time:

https://idea89560041.github.io/Paper-Radar/

For exploratory browsing, the GitHub Actions manual run can temporarily backfill recent years; the scheduled daily run still uses the latest 14-day window.

It searches PubMed, arXiv preprints, Semantic Scholar, and Crossref metadata from flagship journal families, top medical-imaging journals, and major AI conferences. It scores papers against the research profile in `config.yaml`, filters out papers already shown in previous runs, and publishes a static web page plus `papers.json`.

The page groups papers into flagship main journals, flagship-family subjournals, top medical-imaging / AI venues, preprints, and other relevant journals. Traditional neuroscience papers without AI/imaging methods, BCI/EEG-only papers, broad review papers, and low-priority venues such as Scientific Reports or Frontiers journals are filtered out.
