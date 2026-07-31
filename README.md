# Neurodegenerative PET/MRI Deep Learning Paper Radar

This repository powers a daily GitHub Pages dashboard for recent deep learning papers related to neurodegenerative disease imaging research.

The radar focuses on deep learning applications in Alzheimer disease, dementia, MCI, Parkinson disease, Lewy body disease, frontotemporal dementia, and related neurodegenerative disorders. Imaging emphasis is brain MRI/fMRI, brain PET including Aβ-PET / amyloid-beta PET, tau PET, and FDG PET, and whole-body or total-body PET/MRI. Nature, Science, Cell, and npj-family journals are prioritized.

The site is updated automatically every day at about 08:00 China/Hong Kong/Singapore time:

https://idea89560041.github.io/Paper-Radar/

For exploratory browsing, the GitHub Actions manual run can temporarily backfill recent years; the scheduled daily run still uses the latest 14-day window.

It searches PubMed, arXiv preprints, Semantic Scholar, and Crossref metadata from major journals, scores papers against the research profile in `config.yaml`, filters out papers already shown in previous runs, and publishes a static web page plus `papers.json`.

The page groups papers into flagship main journals, flagship-family subjournals, top medical-imaging / AI venues, preprints, and other relevant journals. Traditional neuroscience papers, BCI/EEG-only papers, multi-organ diagnosis papers, image-quality-assessment papers, broad review papers, and low-priority venues such as Scientific Reports or Frontiers journals are filtered out.
