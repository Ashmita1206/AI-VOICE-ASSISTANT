"""
Intent Classifier
=================

Combines pattern matching and keyword scoring to determine the best
intent for a given normalised utterance. Handles compound commands
(e.g., "do X and do Y") by splitting on the conjunction and selecting
the most specific intent.

Usage
-----
    from agent.intent_classifier import IntentClassifier

    classifier = IntentClassifier()
    command = classifier.classify("open chrome and search machine learning")
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace
from typing import Any

from agent.schemas import CommandIntent, IntentDefinition, IntentPattern
from agent.command_registry import get_all_intents, get_intent
from agent.preprocess import normalize_text, tokenize
from agent.entity_extractor import EntityExtractor

logger = logging.getLogger(__name__)


class IntentClassifier:
    """Classifies user utterances into structured intents.

    Features:
        - Compound command splitting ("and")
        - Pattern matching coverage scoring
        - Keyword overlap scoring
        - Fallback handling (confidence threshold)
    """

    def __init__(self, confidence_threshold: float = 0.40):
        self.threshold = confidence_threshold
        self.extractor = EntityExtractor()
        
        # Load registry
        self.intents = get_all_intents()
        self.unknown_intent = get_intent("unknown")
        
        # Build keyword sets for faster lookup
        self._keyword_sets = {
            defn.name: set(defn.keywords) for defn in self.intents if defn.name != "unknown"
        }

    def classify(self, text: str) -> CommandIntent:
        """Process raw text end-to-end and return the best CommandIntent."""
        norm_text = normalize_text(text)
        if not norm_text:
            return CommandIntent(
                intent="unknown",
                entities={},
                confidence=0.0,
                raw_text=text
            )

        # 0. Strict routing for File Explorer Context Search
        # Must not break notepad, browser, or whatsapp.
        find_verbs = r"(find|search|locate|look\s+for|open|where\s+is|need|show\s+me)"
        doc_nouns = r"(file(?!\s*manager)|document|report|proposal|presentation|pdf|ppt|word|excel|spreadsheet|invoice|notes?(?!pad)|notebook(?!s)|deck)"
        if re.search(find_verbs, norm_text, re.IGNORECASE) and re.search(doc_nouns, norm_text, re.IGNORECASE):
            # Check for negative intent words to prevent hijacking notepad or basic app launching
            negative_words = r"\b(notepad|open\s+notes|create\s+file|edit\s+txt|write|type)\b"
            if not re.search(negative_words, norm_text, re.IGNORECASE):
                query_text = norm_text
                query_text = re.sub(rf"^(?:can\s+you\s+)?{find_verbs}\s+(?:the\s+|my\s+|a\s+)?{doc_nouns}(?:s)?\s+(?:about\s+|on\s+|for\s+)?", "", query_text, flags=re.IGNORECASE)
                query_text = re.sub(rf"^(?:can\s+you\s+)?{find_verbs}\s+(?:the\s+|my\s+|a\s+)?", "", query_text, flags=re.IGNORECASE)
                return CommandIntent(
                    intent="find_document_by_context",
                    entities={"query": query_text.strip() or norm_text},
                    confidence=1.0,
                    raw_text=text
                )

        # 1. Handle compound commands (e.g. "open chrome and search ml")
        # We split by " and " (which is the normalised form of "aur", etc.)
        parts = [p.strip() for p in norm_text.split(" and ") if p.strip()]
        
        best_overall: CommandIntent | None = None
        
        # 2. Classify each part independently and aggregate entities, 
        # picking the "most specific" intent as the primary one.
        merged_entities = {}
        for part in parts:
            candidates = self.rank_intents(part)
            if not candidates:
                continue
                
            top_candidate = candidates[0]
            
            # Extract entities for this top candidate
            entities = self.extractor.extract_entities(
                text=part,
                intent_name=top_candidate["intent"].name,
                regex_entities=top_candidate["regex_entities"]
            )
            merged_entities.update(entities)
            
            # Select best intent based on confidence.
            # We prefer web/utility intents over simple app opens if they are part of a compound
            # e.g. "open chrome and search ML" -> search_web is the primary intent.
            if best_overall is None or top_candidate["confidence"] > best_overall.confidence:
                best_overall = CommandIntent(
                    intent=top_candidate["intent"].name,
                    entities={}, # updated later
                    confidence=top_candidate["confidence"],
                    raw_text=text
                )
            elif best_overall.intent == "open_application" and top_candidate["intent"].name != "open_application":
                # Override generic app open with specific action if confidence is acceptable
                if top_candidate["confidence"] >= self.threshold:
                    best_overall = replace(best_overall, intent=top_candidate["intent"].name, confidence=top_candidate["confidence"])

        # Priority Rule: Telegram commands (both open application and messaging)
        raw_clean = text.lower()
        if "telegram" in norm_text or "telegram" in raw_clean:
            open_verbs = r"^(?:open|launch|start|check|kholo|chalao)\s+telegram(?:\s+desktop)?$"
            open_verbs_suffix = r"^telegram(?:\s+desktop)?\s+(?:open|kholo|chalao|start|launch)(?:\s+karo|\s+kar\s+do)?$"
            is_open_cmd = bool(re.match(open_verbs, norm_text)) or bool(re.match(open_verbs_suffix, norm_text)) or \
                          bool(re.match(open_verbs, raw_clean)) or bool(re.match(open_verbs_suffix, raw_clean))

            if is_open_cmd:
                # Force open_application for Telegram opening commands
                return CommandIntent(
                    intent="open_application",
                    entities={"application": "telegram"},
                    confidence=1.0,
                    raw_text=text
                )
            else:
                comm_words = ("send", "message", "tell", "text", "bhejo", "saying", "bol do", "bol", "bhej")
                if any(w in norm_text for w in comm_words) or any(w in raw_clean for w in comm_words):
                    from automation.telegram.nlu import parse_telegram_input
                    res = parse_telegram_input("NEW_COMMAND", text)
                    if not getattr(res, "recipient_query", None):
                        res = parse_telegram_input("NEW_COMMAND", norm_text)

                    entities = {}
                    if getattr(res, "recipient_query", None):
                        entities["contact"] = res.recipient_query
                    if getattr(res, "message_text", None):
                        entities["message"] = res.message_text

                    return CommandIntent(
                        intent="send_telegram_message",
                        entities=entities,
                        confidence=0.95,
                        raw_text=text
                    )

        if not best_overall or best_overall.confidence < self.threshold:
            return CommandIntent(
                intent="unknown",
                entities={},
                confidence=best_overall.confidence if best_overall else 0.0,
                raw_text=text
            )

        best_overall = replace(best_overall, entities=merged_entities)
        
        # Re-resolve intent if entities dictate (e.g. open_application with a website entity -> open_website)
        if best_overall.intent == "open_application" and "website" in best_overall.entities:
            best_overall = replace(best_overall, intent="open_website")

        # Re-resolve intent based on application target (e.g. search on Spotify -> play_music)
        if best_overall.intent in ("search_web", "open_application", "send_message", "open_resource") and "application" in best_overall.entities:
            app_val = best_overall.entities["application"].lower().strip()
            if "spotify" in app_val:
                best_overall = replace(best_overall, intent="play_music")
            elif "whatsapp" in app_val and best_overall.intent in ("send_message", "open_resource"):
                best_overall = replace(best_overall, intent="send_message")

        return best_overall


    def rank_intents(self, text: str) -> list[dict[str, Any]]:
        """Rank all intents against the normalized text."""
        tokens = set(tokenize(text))
        num_tokens = len(tokens)
        if num_tokens == 0:
            return []

        results = []
        for defn in self.intents:
            if defn.name == "unknown":
                continue

            # A. Pattern Matching
            best_pattern_score = 0.0
            best_regex_entities = {}
            best_pattern = None

            for pattern in defn.patterns:
                match = pattern.regex.fullmatch(text)
                if match:
                    # Perfect match. Score based on how specific it is (fewer entity slots = more specific)
                    slots = len(pattern.slots)
                    # Base score is 1.0 for a match. Add tiny bonus for zero-slot exact matches
                    bonus = 0.05 if slots == 0 else 0.0
                    score = 1.0 + bonus
                    
                    if score > best_pattern_score:
                        best_pattern_score = score
                        best_regex_entities = match.groupdict()
                        best_pattern = pattern
                else:
                    # Partial match attempt (coverage)
                    # We search the regex anywhere in the text
                    # Strip ^ and $ from the compiled regex pattern
                    unanchored = pattern.regex.pattern
                    if unanchored.startswith("^"): unanchored = unanchored[1:]
                    if unanchored.endswith("$"): unanchored = unanchored[:-1]
                    
                    match_search = re.search(unanchored, text, re.IGNORECASE)
                    if match_search:
                        # How much of the text did it cover?
                        span = match_search.span()
                        coverage = (span[1] - span[0]) / max(len(text), 1)
                        if coverage > best_pattern_score:
                            best_pattern_score = coverage
                            best_regex_entities = match_search.groupdict()
                            best_pattern = pattern

            # B. Keyword Scoring
            keywords = self._keyword_sets.get(defn.name, set())
            overlap = tokens.intersection(keywords)
            # Use max(1, min(...)) so short utterances aren't penalized
            denominator = max(1, min(len(keywords), num_tokens))
            keyword_score = len(overlap) / denominator

            # C. Confidence Calculation
            confidence = self.calculate_confidence(best_pattern_score, keyword_score)

            results.append({
                "intent": defn,
                "confidence": round(confidence, 2),
                "pattern_score": best_pattern_score,
                "keyword_score": keyword_score,
                "regex_entities": best_regex_entities,
                "pattern_matched": best_pattern.template if best_pattern else None
            })

        # Sort descending by confidence
        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results

    def calculate_confidence(self, pattern_score: float, keyword_score: float) -> float:
        """Combine pattern and keyword scores."""
        # Cap pattern score at 1.0 for the weighted sum (bonus is kept for comparison, but capped here)
        p_score = min(1.0, pattern_score)
        k_score = min(1.0, keyword_score)
        
        # 70% weight to pattern match, 30% to keywords
        base = (0.7 * p_score) + (0.3 * k_score)
        
        # If pattern score is > 1.0 (exact match bonus), add it on top
        if pattern_score > 1.0:
            base += (pattern_score - 1.0)
            
        return min(1.0, base)
