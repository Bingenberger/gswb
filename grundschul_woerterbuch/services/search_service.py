import re
from difflib import SequenceMatcher

try:
    from rapidfuzz import fuzz, process
except ImportError:  # pragma: no cover - Fallback fuer sehr kleine lokale Setups.
    fuzz = None
    process = None


class SearchService:
    def __init__(self, repository):
        self.repository = repository
        self._search_terms_cache = None

    def invalidate_cache(self):
        self._search_terms_cache = None

    def _get_search_terms(self):
        if self._search_terms_cache is None:
            self._search_terms_cache = self.repository.get_search_terms()
        return self._search_terms_cache

    @staticmethod
    def normalize(text):
        if not text:
            return ""
        normalized = text.strip().lower()
        replacements = {
            "ä": "ae",
            "ö": "oe",
            "ü": "ue",
            "ß": "ss",
        }
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)
        normalized = re.sub(r"[^a-z0-9]+", "", normalized)
        return normalized

    def resolve_query(self, query):
        normalized = self.normalize(query)
        if not normalized:
            return {"match": None, "suggestions": []}

        direct_match = self.repository.get_word_by_normalized_lemma(normalized)
        if direct_match:
            return {"match": direct_match, "suggestions": []}

        misspelling_match = self.repository.get_word_by_misspelling(normalized)
        if misspelling_match:
            return {"match": misspelling_match, "suggestions": []}

        suggestions = self.autocomplete(query)
        exact_suggestion = next((item for item in suggestions if item["lemma_normalized"] == normalized), None)
        if exact_suggestion:
            return {"match": {"lemma": exact_suggestion["lemma"]}, "suggestions": suggestions}

        return {"match": None, "suggestions": suggestions}

    def autocomplete(self, query, limit=8):
        normalized = self.normalize(query)
        if not normalized:
            return []

        suggestions = []
        seen = set()

        direct_match = self.repository.get_word_by_normalized_lemma(normalized)
        if direct_match:
            self._add_suggestion(
                suggestions,
                seen,
                direct_match["lemma"],
                direct_match["part_of_speech"],
                "exact",
            )

        prefix_matches = self.repository.get_prefix_matches(normalized, limit=limit)
        for item in prefix_matches:
            match_type = "exact" if self.normalize(item["lemma"]) == normalized else "prefix"
            self._add_suggestion(suggestions, seen, item["lemma"], item["part_of_speech"], match_type)

        misspelling_matches = self.repository.get_misspelling_prefix_matches(normalized, limit=limit)
        for item in misspelling_matches:
            self._add_suggestion(suggestions, seen, item["lemma"], item["part_of_speech"], "fehlschreibung")

        fuzzy_matches = self._fuzzy_candidates(normalized, limit=limit)
        for item in fuzzy_matches:
            self._add_suggestion(
                suggestions,
                seen,
                item["lemma"],
                item["part_of_speech"],
                "meintest-du",
                score=item["score"],
            )

        return suggestions[:limit]

    def _add_suggestion(self, suggestions, seen, lemma, part_of_speech, match_type, score=None):
        if lemma in seen:
            return
        seen.add(lemma)
        suggestions.append(
            {
                "lemma": lemma,
                "lemma_normalized": self.normalize(lemma),
                "part_of_speech": part_of_speech,
                "match_type": match_type,
                "score": score,
            }
        )

    def _fuzzy_candidates(self, normalized_query, limit=8):
        search_terms = self._get_search_terms()
        choices = {}

        for word in search_terms["words"]:
            choices[word["normalized_lemma"]] = {
                "lemma": word["lemma"],
                "part_of_speech": word["part_of_speech"],
            }

        for variant in search_terms["misspellings"]:
            choices.setdefault(
                variant["variant"],
                {"lemma": variant["lemma"], "part_of_speech": variant["part_of_speech"]},
            )

        if process and fuzz:
            matches = process.extract(
                normalized_query,
                choices.keys(),
                scorer=fuzz.WRatio,
                limit=limit,
                score_cutoff=70,
            )
        else:
            scored = []
            for key in choices:
                score = int(SequenceMatcher(None, normalized_query, key).ratio() * 100)
                if score >= 70:
                    scored.append((key, score, None))
            matches = sorted(scored, key=lambda item: item[1], reverse=True)[:limit]

        fuzzy_results = []
        added = set()
        for key, score, _ in matches:
            item = choices[key]
            if item["lemma"] in added:
                continue
            fuzzy_results.append(
                {
                    "lemma": item["lemma"],
                    "part_of_speech": item["part_of_speech"],
                    "score": score,
                }
            )
            added.add(item["lemma"])
        return fuzzy_results
