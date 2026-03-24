import unittest

from core.interpretation import build_stock_interpretation


class TestInterpretation(unittest.TestCase):
    def test_builds_top_drivers_and_horizon_views(self):
        signals = [
            {
                "event": "Iran conflict escalates",
                "event_type": "geopolitical",
                "direct_effect": "Oil prices rise",
                "macro_impact": "Inflation expectations rise",
                "market_reaction": "Risk-off in equities",
                "stock_specific_impact": "Industrial stocks sold",
                "time_horizon": "short",
                "confidence": "high",
                "relevance_score": 82,
                "impact_score": 90,
                "sentiment": "negativ",
                "link": "https://example.com/1",
                "causal_chain": "a -> b -> c -> d",
            },
            {
                "event": "Order backlog stays strong",
                "event_type": "company",
                "direct_effect": "Visibility improves",
                "macro_impact": "Demand remains stable",
                "market_reaction": "Supportive for quality industrials",
                "stock_specific_impact": "Downside partly cushioned",
                "time_horizon": "long",
                "confidence": "medium",
                "relevance_score": 70,
                "impact_score": 72,
                "sentiment": "positiv",
                "link": "https://example.com/2",
                "causal_chain": "e -> f -> g -> h",
            },
        ]

        result = build_stock_interpretation("Siemens Energy", "-7.00%", signals)
        self.assertIn("top_drivers", result)
        self.assertGreaterEqual(len(result["top_drivers"]), 1)
        self.assertIn("Kurzfristig", result["short_term"])
        self.assertIn("Langfristig", result["long_term"])
        self.assertIn("Kursbewegung", result["price_move_explained"])

    def test_no_signals_returns_safe_fallback(self):
        result = build_stock_interpretation("Microsoft", "+0.50%", [])
        self.assertEqual(result["overall"], "neutral")
        self.assertEqual(result["top_drivers"], [])


if __name__ == "__main__":
    unittest.main()
