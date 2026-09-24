import unittest
from unittest.mock import Mock, patch

import paper_bot as bot


class RetrievalTests(unittest.TestCase):
    def test_diffusion_mri_segmentation_topic_is_prioritized(self):
        cfg = bot.load_config("config.yaml")
        paper = bot.Paper(
            source="arXiv",
            title="Transformer-based diffusion MRI white matter tract segmentation",
            authors=[],
            abstract="We parcellate fiber bundles from dMRI tractography using deep learning.",
            url="https://arxiv.org/abs/2609.12345",
            published_date="2026-09-20",
            query="diffusion MRI segmentation parcellation",
            venue="arXiv",
        )
        scored = bot.score_paper(paper, cfg)
        self.assertGreaterEqual(scored.score, cfg["scoring"]["min_score"])
        self.assertEqual(bot.infer_topic(scored), "Diffusion MRI Segmentation / Parcellation")

    def test_new_topic_queries_fit_source_limits(self):
        cfg = bot.load_config("config.yaml")
        profile = cfg["research_profile"]
        self.assertLessEqual(
            len(profile["pubmed_queries"]) + len(bot.build_pubmed_top_journal_queries(cfg)),
            cfg["sources"]["pubmed"]["max_queries"],
        )
        self.assertLessEqual(len(profile["arxiv_queries"]), cfg["sources"]["arxiv"]["max_queries"])
        self.assertLessEqual(
            len(profile["semantic_scholar_queries"]),
            cfg["sources"]["semantic_scholar"]["max_queries"],
        )

    def test_flagship_brain_imaging_without_ai_terms_is_retained(self):
        cfg = bot.load_config("config.yaml")
        cases = [
            bot.Paper(
                source="Crossref Top Journals",
                title="White matter micro- and macrostructure brain charts for the human lifespan",
                authors=[],
                abstract="By processing and standardizing 35,120 brain scans, we mapped white matter pathways across life.",
                url="https://doi.org/10.1038/s41586-026-10454-2",
                published_date="2026-05-13",
                query="flagship brain imaging",
                venue="Nature",
                doi="10.1038/s41586-026-10454-2",
            ),
            bot.Paper(
                source="PubMed",
                title="Lifespan normative modeling of brain microstructure",
                authors=[],
                abstract="A normative model based on diffusion MRI and DTI detects MCI and Alzheimer's disease deviations while accounting for scanning protocol parameters.",
                url="https://doi.org/10.1038/s41467-026-72875-x",
                published_date="2026-05-27",
                query="flagship brain imaging",
                venue="Nature Communications",
                doi="10.1038/s41467-026-72875-x",
            ),
        ]
        for paper in cases:
            scored = bot.score_paper(paper, cfg)
            self.assertGreaterEqual(scored.score, cfg["scoring"]["min_score"])
            self.assertIn("priority-brain-imaging-venue", scored.reasons)

    def test_non_flagship_neuroscience_without_ai_is_still_rejected(self):
        cfg = bot.load_config("config.yaml")
        paper = bot.Paper(
            source="PubMed",
            title="White matter brain charts across the lifespan",
            authors=[],
            abstract="Diffusion MRI measurements of normal brain development.",
            url="https://example.org/paper",
            published_date="2026-05-13",
            query="brain imaging",
            venue="Journal of General Neuroscience",
        )
        self.assertEqual(bot.score_paper(paper, cfg).reasons, ["missing-ai-dl-method"])

    def test_protocol_article_is_excluded_by_title(self):
        cfg = bot.load_config("config.yaml")
        paper = bot.Paper(
            source="PubMed",
            title="Protocol for deep learning analysis of brain MRI",
            authors=[],
            abstract="Brain MRI segmentation study.",
            url="https://example.org/protocol",
            published_date="2026-09-01",
            query="brain MRI",
            venue="Nature Communications",
        )
        self.assertEqual(bot.score_paper(paper, cfg).reasons, ["hard-exclude:protocol"])

    def test_top_journal_queries_include_broad_brain_imaging_safety_net(self):
        cfg = bot.load_config("config.yaml")
        queries = bot.build_pubmed_top_journal_queries(cfg)
        self.assertTrue(any('"brain scans"[Title/Abstract]' in query for query in queries))
        self.assertTrue(any('"normative modeling"[Title/Abstract]' in query for query in queries))

    def test_long_ncbi_query_uses_post_and_retries(self):
        limited = Mock(status_code=429, headers={"retry-after": "0"})
        success = Mock(status_code=200)
        success.json.return_value = {"esearchresult": {"idlist": ["123"]}}
        params = {"term": "brain " * 1000}
        with patch.object(bot.requests, "post", side_effect=[limited, success]) as post, \
                patch.object(bot.requests, "get") as get:
            result = bot.requests_get_json("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi", params=params)
        self.assertEqual(result["esearchresult"]["idlist"], ["123"])
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.call_args.kwargs["data"], params)
        get.assert_not_called()

    def test_pubmed_full_journal_name_survives_selection(self):
        cfg = bot.load_config("config.yaml")
        cfg["sources"]["pubmed"].update(max_queries=1, sleep_seconds=0)
        xml = '''<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>123</PMID>
        <Article><ArticleTitle>Deep learning for brain MRI</ArticleTitle>
        <Abstract><AbstractText>Brain MRI deep learning segmentation.</AbstractText></Abstract>
        <Journal><Title>Nature Machine Intelligence</Title><ISOAbbreviation>Nat Mach Intell</ISOAbbreviation></Journal>
        </Article></MedlineCitation></PubmedArticle></PubmedArticleSet>'''
        with patch.object(bot, "requests_get_json", return_value={"esearchresult": {"idlist": ["123"]}}), \
                patch.object(bot, "requests_get_text", return_value=xml):
            papers = bot.fetch_pubmed(cfg)
        self.assertEqual(papers[0].venue, "Nature Machine Intelligence")
        self.assertEqual(bot.classify_venue_category(papers[0], cfg), "flagship_subjournal")
        self.assertEqual(len(bot.select_diverse_papers(papers, cfg)), 1)

    def test_crossref_budget_covers_multiple_topics(self):
        cfg = {"sources": {"crossref_top_journals": {"max_calls": 3, "sleep_seconds": 0}},
               "top_journal_families": {"crossref_journals": ["Nature", "Science", "Cell"],
                                        "crossref_topic_queries": ["brain", "world model", "trajectory"]}}
        with patch.object(bot, "requests_get_json", return_value={"message": {"items": []}}) as get:
            bot.fetch_crossref_top_journals(cfg)
        self.assertEqual({call.kwargs["params"]["query.bibliographic"] for call in get.call_args_list},
                         {"brain", "world model", "trajectory"})

    def test_total_fetch_failure_does_not_look_like_success(self):
        with patch.object(bot, "safe_fetch", return_value=[]):
            with self.assertRaisesRegex(RuntimeError, "refusing to publish"):
                bot.fetch_score_sort_papers({})


if __name__ == "__main__":
    unittest.main()
