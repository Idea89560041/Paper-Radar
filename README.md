# Brain Image / Neuroimage Paper Radar

This repository powers a daily GitHub Pages dashboard for recent brain image, neuroimage, and high-value medical imaging papers.

The radar prioritizes computational imaging and AI papers involving Brain image / Neuroimage data, not only disease diagnosis or large models. MRI, fMRI, PET, Aβ-PET / amyloid-beta PET, segmentation, registration, reconstruction, denoising, super-resolution, harmonization, synthesis, image translation, image generation, diffusion or generative models, AI agents, vision-language models, foundation models, diagnosis, prognosis, and prediction are all in scope. It also tracks whole-body and total-body PET/MRI papers on multi-organ change, longitudinal trajectories, dynamic PET, and kinetic or parametric imaging.

The site is updated automatically every day at about 08:00 China/Hong Kong/Singapore time:

https://idea89560041.github.io/Paper-Radar/

For exploratory browsing, the GitHub Actions manual run can temporarily backfill recent years; the scheduled daily run uses a 180-day rolling window with sent-state deduplication.

It searches PubMed, arXiv preprints, Semantic Scholar, and Crossref metadata from flagship journal families, top medical-imaging journals, and major AI conferences. It scores papers against the research profile in `config.yaml`, filters out papers already shown in previous runs, and publishes a static web page plus `papers.json`.

The page focuses on flagship main journals, flagship-family subjournals, top medical-imaging / AI venues, and selected preprints. Traditional neuroscience papers without AI/imaging methods, BCI/EEG-only papers, broad review papers, and low-priority venues such as Scientific Reports or Frontiers journals are filtered out.
