import unittest

from utils.news_memory import (
    build_title_fingerprint,
    canonicalize_url,
    cosine_similarity,
    normalize_text,
)


class TestNewsMemory(unittest.TestCase):
    def test_canonicalize_url_removes_tracking_params(self):
        url = "https://www.example.com/news?id=1&utm_source=abc&fbclid=xyz&ref=foo"
        canonical = canonicalize_url(url)
        self.assertEqual(canonical, "https://example.com/news?id=1")

    def test_title_fingerprint_is_stable_across_case_and_punctuation(self):
        a = build_title_fingerprint("Microsoft beats Earnings!")
        b = build_title_fingerprint("microsoft beats earnings")
        self.assertEqual(a, b)

    def test_cosine_similarity_basics(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [1.0, 0.0]), 1.0, places=6)
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0, places=6)

    def test_normalize_text_collapses_whitespace(self):
        self.assertEqual(normalize_text("  hello,\n  WORLD! "), "hello world")


if __name__ == "__main__":
    unittest.main()
