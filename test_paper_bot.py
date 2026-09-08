import unittest
from unittest.mock import Mock, patch

import paper_bot as bot


class RetrievalTests(unittest.TestCase):
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
