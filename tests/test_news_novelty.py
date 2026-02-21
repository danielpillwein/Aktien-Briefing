import unittest
from unittest.mock import patch

NEWS_NOVELTY_IMPORT_ERROR = None
try:
    from core.news_novelty import filter_news_by_novelty
    from utils.news_memory import build_memory_entry
except ModuleNotFoundError as exc:
    NEWS_NOVELTY_IMPORT_ERROR = exc


@unittest.skipIf(NEWS_NOVELTY_IMPORT_ERROR is not None, f"optional dependency missing: {NEWS_NOVELTY_IMPORT_ERROR}")
class TestNewsNovelty(unittest.IsolatedAsyncioTestCase):
    async def test_day2_duplicate_quarterly_news_is_filtered(self):
        memory = {"version": 1, "entries": []}
        day1_article = {
            "title": "Microsoft Q4 Earnings Beat Expectations",
            "content": "Microsoft reports strong quarterly earnings with cloud growth.",
            "link": "https://news.example.com/microsoft-q4?utm_source=a",
            "source_name": "Example",
        }
        memory["entries"].append(
            build_memory_entry(
                stock_name="Microsoft",
                article=day1_article,
                summary_text="Microsoft reported strong quarterly earnings.",
                topic_embedding=[1.0, 0.0],
                date_sent="2026-02-20T07:00:00",
            )
        )

        day2_articles = [
            {
                "title": "MSFT posts strong quarterly results",
                "content": "Quarterly earnings were strong and cloud revenue increased.",
                "link": "https://another.example.com/msft-earnings",
                "source_name": "Another",
            }
        ]
        cfg = {
            "lookback_days": 14,
            "semantic_threshold": 0.86,
            "exact_url_dedupe": True,
            "exact_title_dedupe": True,
        }

        with patch("core.news_novelty._embed_texts", return_value=[[0.99, 0.01]]):
            result = await filter_news_by_novelty("Microsoft", day2_articles, memory, cfg)

        self.assertEqual(result["stats"]["new_count"], 0)
        self.assertEqual(result["stats"]["semantic_dupes"], 1)

    async def test_when_only_two_new_articles_exist_only_two_are_returned(self):
        memory = {"version": 1, "entries": []}
        raw_articles = [
            {"title": "Nvidia launches new chip", "content": "new architecture", "link": "https://a.com/1"},
            {"title": "Nvidia expands foundry partnership", "content": "capacity expansion", "link": "https://a.com/2"},
        ]
        cfg = {
            "lookback_days": 14,
            "semantic_threshold": 0.86,
            "exact_url_dedupe": True,
            "exact_title_dedupe": True,
        }

        with patch("core.news_novelty._embed_texts", return_value=[[1.0, 0.0], [0.0, 1.0]]):
            result = await filter_news_by_novelty("Nvidia", raw_articles, memory, cfg)

        self.assertEqual(len(result["new_items"]), 2)
        self.assertEqual(result["stats"]["new_count"], 2)

    async def test_exact_duplicate_link_is_filtered_without_embedding(self):
        memory = {"version": 1, "entries": []}
        article = {
            "title": "Alphabet AI update",
            "content": "Gemini update details",
            "link": "https://news.example.com/alphabet-ai?utm_source=x",
            "source_name": "Example",
        }
        memory["entries"].append(
            build_memory_entry(
                stock_name="Alphabet",
                article=article,
                summary_text="Alphabet shared AI updates.",
                topic_embedding=[],
                date_sent="2026-02-20T07:00:00",
            )
        )

        cfg = {
            "lookback_days": 14,
            "semantic_threshold": 0.86,
            "exact_url_dedupe": True,
            "exact_title_dedupe": True,
        }

        with patch("core.news_novelty._embed_texts", return_value=None):
            result = await filter_news_by_novelty("Alphabet", [article], memory, cfg)

        self.assertEqual(result["stats"]["exact_dupes"], 1)
        self.assertEqual(result["stats"]["new_count"], 0)


if __name__ == "__main__":
    unittest.main()
