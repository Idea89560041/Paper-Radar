# Brain Image / Neuroimage Paper Radar

This repository powers a daily GitHub Pages dashboard for recent brain image, neuroimage, and high-value medical imaging papers.

The radar prioritizes computational imaging and AI papers involving Brain image / Neuroimage data, including diffusion MRI segmentation and parcellation, white-matter tract or bundle segmentation, MRI, fMRI, PET, Aβ-PET, medical imaging world models, foundation models, diagnosis, prognosis, and prediction. It also tracks brain-centered multi-organ longitudinal trajectories, brain-body / brain-organ axes, and whole-body or total-body PET/MRI.

The site is updated automatically every day at about 08:00 China/Hong Kong/Singapore time:

https://idea89560041.github.io/Paper-Radar/

For exploratory browsing, the GitHub Actions manual run can temporarily backfill recent years; the scheduled daily run uses a 180-day rolling window with sent-state deduplication.

It searches PubMed, arXiv preprints, Semantic Scholar, and Crossref metadata from flagship journal families, top medical-imaging journals, and major AI conferences. It scores papers against the research profile in `config.yaml`, filters out papers already shown in previous runs, and publishes a static web page plus `papers.json`.

The page focuses on flagship main journals, flagship-family subjournals, top medical-imaging / AI venues, and selected preprints. Traditional neuroscience papers without AI/imaging methods, BCI/EEG-only papers, broad review papers, and low-priority venues such as Scientific Reports or Frontiers journals are filtered out.
