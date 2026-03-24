import unittest

from core.news_ranking import rank_articles_for_stock, score_article_relevance


class TestNewsRanking(unittest.TestCase):
    def test_recent_article_scores_higher_than_old_article(self):
        stock = "Microsoft"
        recent = {
            "title": "Microsoft raises AI guidance",
            "content": "Revenue guidance up 12% as AI demand remains strong.",
            "published_at": "2030-01-01T08:00:00+0000",
            "source_name": "Reuters",
            "link": "https://reuters.com/example",
        }
        old = {
            "title": "Microsoft update",
            "content": "Company update.",
            "published_at": "2020-01-01T08:00:00+0000",
            "source_name": "Unknown Blog",
            "link": "https://example.org/post",
        }
        cfg = {"min_relevance_score": 0, "max_candidates_per_stock": 10}

        recent_score = score_article_relevance(stock, recent, cfg)
        old_score = score_article_relevance(stock, old, cfg)

        self.assertGreater(recent_score, old_score)

    def test_rank_respects_threshold_and_max_candidates(self):
        articles = [
            {
                "title": "Visa expands cross-border payments",
                "content": "Cross-border volume and margin improved by 8%.",
                "published_at": "2030-01-01T08:00:00+0000",
                "source_name": "Bloomberg",
                "link": "https://bloomberg.com/a",
            },
            {
                "title": "Random unrelated note",
                "content": "No numbers, no stock context",
                "published_at": "2020-01-01T08:00:00+0000",
                "source_name": "Unknown",
                "link": "https://example.com/b",
            },
            {
                "title": "Visa sees inflation pressure",
                "content": "Inflation and rates affect demand.",
                "published_at": "2030-01-01T07:00:00+0000",
                "source_name": "Reuters",
                "link": "https://reuters.com/c",
            },
        ]
        cfg = {
            "min_relevance_score": 40,
            "max_candidates_per_stock": 1,
        }

        ranked = rank_articles_for_stock("Visa", articles, cfg)
        self.assertLessEqual(len(ranked), 1)
        if ranked:
            self.assertGreaterEqual(ranked[0]["relevance_score"], 40)


if __name__ == "__main__":
    unittest.main()
