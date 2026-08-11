"""
Discovery Manager
=================

Provides fuzzy search query matching, user preference overrides, ranking engine,
and best resource resolution for desktop agents.
"""

import os
import json
import re
import difflib
import logging
import copy
from typing import List, Dict, Any, Optional, Tuple

from agentic.discovery.schemas import Resource
from agentic.discovery.indexer import get_indexer, CACHE_DIR

logger = logging.getLogger(__name__)

PREFERENCES_PATH = os.path.join(CACHE_DIR, "preferences.json")

def load_user_preferences() -> Dict[str, Dict[str, Any]]:
    """Load user preferences mapping resource names to types (e.g. website, application)."""
    if os.path.exists(PREFERENCES_PATH):
        try:
            with open(PREFERENCES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.debug(f"Failed to load user preferences: {e}")
    return {}

def is_abbreviation(abbr: str, full: str) -> bool:
    """Check if abbr is an abbreviation of full name (e.g. 'vscode' -> 'visual studio code')."""
    abbr = abbr.lower().replace(" ", "").replace("-", "")
    full = full.lower().replace("-", " ")
    full_words = full.split()
    
    # 1. Direct initials matching
    initials = "".join(w[0] for w in full_words if w)
    if abbr == initials:
        return True
        
    # 2. Initials + suffix matching (e.g. 'vs' + 'code' = 'vscode')
    for i in range(1, len(full_words)):
        prefix_initials = "".join(w[0] for w in full_words[:i])
        if w := full_words[i:]:
            last_word = w[0]
            if abbr.startswith(prefix_initials):
                suffix = abbr[len(prefix_initials):]
                if last_word.startswith(suffix):
                    return True
                
    # 3. Common aliases
    try:
        from execution.applications import CANONICAL_ALIASES
        for canonical, aliases in CANONICAL_ALIASES.items():
            if abbr in [a.replace(" ", "") for a in aliases] and full.replace(" ", "") == canonical.replace(" ", ""):
                return True
    except ImportError:
        pass
        
    return False

def discover(query: str) -> List[Resource]:
    """Find all matching resources from the index, returning their matching confidence scores."""
    indexer = get_indexer()
    resources = indexer.load_index()
    
    query = query.lower().strip()
    if not query:
        return []
        
    matches = []
    
    for res in resources:
        name = res.name.lower().strip()
        score = 0.0
        
        # 1. Exact match
        if query == name:
            score = 1.0
            
        # 2. Normalized alphanumeric match
        else:
            q_norm = "".join(c for c in query if c.isalnum())
            n_norm = "".join(c for c in name if c.isalnum())
            
            if q_norm == n_norm:
                score = 0.95
            elif q_norm in n_norm:
                score = (len(q_norm) / len(n_norm)) * 0.90
            elif n_norm in q_norm:
                # Do NOT allow weak folder substring matches (e.g. folder 'microsoft' matching query 'microsoft store')
                if res.type not in ("folder", "file"):
                    score = (len(n_norm) / len(q_norm)) * 0.85
                
            # 3. Abbreviation / initials check (e.g. "vs code" -> "visual studio code")
            if score == 0.0 and is_abbreviation(query, name):
                score = 0.92
                
            # 4. Word-based prefix matching
            if score == 0.0:
                q_words = query.split()
                n_words = name.split()
                if q_words and n_words:
                    matched_words = 0
                    n_idx = 0
                    for qw in q_words:
                        while n_idx < len(n_words):
                            if n_words[n_idx].startswith(qw):
                                matched_words += 1
                                n_idx += 1
                                break
                            n_idx += 1
                    if matched_words == len(q_words):
                        score = 0.90
                        
            # 5. Fallback to standard SequenceMatcher with high threshold
            if score == 0.0:
                matcher = difflib.SequenceMatcher(None, query, name)
                ratio = matcher.ratio()
                if ratio >= 0.85:
                    score = ratio * 0.75
                    
        # Factor in resource confidence and verify threshold
        if score >= 0.4:
            matched_res = copy.deepcopy(res)
            # Apply base confidence scale
            score_final = score * res.confidence
            if res.type in ("application", "website"):
                score_final *= 1.1
            score_final = min(1.0, round(score_final, 2))
            
            matched_res.confidence = score_final
            matches.append(matched_res)
            
    return matches

def rank_resources(resources: List[Resource], intent: str) -> List[Tuple[Resource, float, str]]:
    """Rank matches based on priority: running apps > installed apps > open browser tab > bookmarks > files/folders.
    
    Returns:
        List of tuples: (Resource, final_score, reasoning_category)
    """
    # Clean intent and split to check for exact word modifiers (avoid matching 'app' in 'whatsapp')
    intent_lower = intent.lower().strip()
    intent_words = re.findall(r"\b\w+\b", intent_lower)
    
    # Check query/intent modifiers
    force_type = None
    if "website" in intent_words:
        force_type = "website"
    elif "app" in intent_words or "application" in intent_words or "launch" in intent_words or "open" in intent_words:
        force_type = "application"
        
    prefs = load_user_preferences()
    
    scored_resources = []
    
    for res in resources:
        res_name_lower = res.name.lower().strip()
        
        # 1. Base category priority
        category_name = "default"
        if res.type == "application":
            if res.is_running:
                priority_base = 100.0
                category_name = "Running application"
            else:
                priority_base = 90.0
                category_name = "Installed desktop application"
        elif res.type == "website":
            if res.source == "open_tabs":
                priority_base = 80.0
                category_name = "Existing browser tab"
            else:
                priority_base = 70.0
                category_name = "Browser bookmark/history"
        else:
            priority_base = 50.0
            category_name = f"Filesystem {res.type}"
            
        # 2. Modify based on intent overrides (forced types)
        reason_modifier = ""
        if force_type:
            if res.type == force_type:
                priority_base += 100.0
                reason_modifier = " (Forced by intent modifier)"
            elif force_type == "application" and res.type in ("folder", "file"):
                priority_base -= 500.0
                reason_modifier = " (Filesystem item excluded for application intent)"
            else:
                priority_base -= 200.0
                reason_modifier = " (Mismatched type due to modifier)"
                
        # 3. Modify based on user preference overrides
        else:
            pref_type = None
            for pref_key, pref_val in prefs.items():
                if pref_key.lower().strip() == res_name_lower:
                    pref_type = pref_val.get("preferred_type")
                    break
            if pref_type:
                if res.type == pref_type:
                    priority_base += 50.0
                    reason_modifier = " (User preference overrides default ranking)"
                else:
                    priority_base -= 50.0
                    reason_modifier = " (Deprioritized by user preference)"
                    
        # Final ranking score: priority_base + match_confidence
        final_score = round(priority_base + res.confidence, 2)
        scored_resources.append((res, final_score, category_name + reason_modifier))
        
    # Sort descending by score
    scored_resources.sort(key=lambda x: x[1], reverse=True)
    return scored_resources

def resolve_best_resource(query: str, intent: str) -> Optional[Resource]:
    """Inspect matches, rank them, log reasoning, and return the resolved highest-priority resource."""
    intent_lower = intent.lower().strip()
    
    # If the user explicitly requested web search only (e.g., "Search ChatGPT")
    if intent_lower.startswith("search "):
        search_query = intent[7:].strip()
        logger.info(f"Explicit web search requested for: '{search_query}'")
        return Resource(
            name=f"Search Google for '{search_query}'",
            type="website",
            source="web_search_fallback",
            url=f"https://www.google.com/search?q={search_query}",
            confidence=1.0
        )
        
    matches = discover(query)
    
    if not matches:
        query_clean = query.lower().strip().replace(" ", "")
        if "chatgpt" in query_clean:
            url = "https://chat.openai.com"
            name = "ChatGPT"
        elif "whatsapp" in query_clean:
            url = "https://web.whatsapp.com"
            name = "WhatsApp"
        else:
            url = f"https://www.google.com/search?q={query}"
            name = f"Search Google for '{query}'"
            
        logger.info(f"No direct matches found for '{query}'. Using browser fallback: {url}")
        return Resource(
            name=name,
            type="website",
            source="web_search_fallback",
            url=url,
            confidence=0.5
        )
        
    ranked = rank_resources(matches, intent)
    
    # Logging reasoning
    print(f"\nUser: {intent}")
    print("\nMatches:")
    for idx, (res, score, category) in enumerate(ranked, 1):
        # Format path/url/executable for display
        loc = res.url or res.executable or res.path or "N/A"
        print(f"{idx}. {res.name} ({res.type}) [source: {res.source}] score={score} running={res.is_running}")
        
    selected_res, selected_score, selected_reason = ranked[0]
    
    print(f"\nSelected:\n{selected_res.name} ({selected_res.type})")
    print(f"Reason:\n{selected_reason}")
    print("-" * 50)
    
    return selected_res

def find_best_resource(query: str, type_filter: Optional[str] = None) -> Optional[Resource]:
    """Backwards-compatible wrapper calling resolve_best_resource."""
    intent = f"open {query}"
    if type_filter == "application":
        intent += " app"
    elif type_filter == "website":
        intent += " website"
        
    res = resolve_best_resource(query, intent)
    
    # Web search fallback means no direct resource matched on system
    if res and res.source == "web_search_fallback":
        return None
        
    if res and type_filter and res.type != type_filter:
        matches = discover(query)
        filtered = [m for m in matches if m.type == type_filter]
        if filtered:
            ranked = rank_resources(filtered, intent)
            if ranked:
                return ranked[0][0]
        return None
        
    return res

def get_system_context() -> Dict[str, Any]:
    """Compile the current resource snapshot of the system for Qwen planner."""
    indexer = get_indexer()
    resources = indexer.load_index()
    
    installed_apps = []
    desktop_entries = []
    recent_files = []
    bookmarks = []
    running_processes = []
    
    for res in resources:
        if res.type == "application":
            if res.source in ("desktop", "start_menu"):
                desktop_entries.append(res.name)
            else:
                installed_apps.append(res.name)
        elif res.type in ("file", "folder"):
            recent_files.append({
                "name": res.name,
                "type": res.type,
                "path": res.path
            })
        elif res.type == "website":
            bookmarks.append({
                "name": res.name,
                "url": res.url,
                "source": res.source
            })
        elif res.type == "process":
            running_processes.append(res.name)
            
    return {
        "installed_apps": list(set(installed_apps))[:30],
        "desktop_entries": list(set(desktop_entries))[:30],
        "recent_files": recent_files[:20],
        "bookmarks": bookmarks[:30],
        "running_processes": running_processes[:20]
    }
