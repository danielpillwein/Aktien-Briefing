import unittest

from core.macro_linker import build_macro_overview


class TestMacroLinker(unittest.TestCase):
    def test_links_macro_factors_to_holdings(self):
        portfolio = [{"name": "Siemens Energy", "ticker": "ENR.DE"}]
        watchlist = [{"name": "Visa Inc.", "ticker": "V"}]
        news = {
            "portfolio": {
                "Siemens Energy": {
                    "items": [
                        {
                            "event": "Iran conflict escalates",
                            "event_type": "geopolitical",
                            "direct_effect": "Oil rises",
                            "macro_impact": "Inflation pressure rises",
                            "market_reaction": "Risk-off",
                            "link": "https://example.com/iran-oil",
                            "affected_sectors": ["Energy", "Industrials"],
                            "impact_score": 88,
                            "relevance_score": 81,
                            "confidence": "high",
                            "time_horizon": "short",
                        }
                    ]
                }
            },
            "watchlist": {"Visa Inc.": {"items": []}},
        }

        result = build_macro_overview(portfolio, watchlist, news)
        self.assertIn("factors", result)
        self.assertGreaterEqual(len(result["factors"]), 1)
        factor = result["factors"][0]
        self.assertIn("Siemens Energy", factor["affected_holdings"])
        self.assertIn("https://example.com/iran-oil", factor["sources"])
        self.assertIn("summary", result)


if __name__ == "__main__":
    unittest.main()
