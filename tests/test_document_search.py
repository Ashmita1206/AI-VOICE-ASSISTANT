"""
Tests — Context-Based Document Search
======================================

Covers:
    1. Scanner — supported/excluded extension filtering
    2. Cache   — init, upsert, get, delete, metadata
    3. Embeddings — extract_text (plain), extract_keywords, extract_summary
    4. Ranking — composite score ordering
    5. Search  — end-to-end with a temporary index
    6. Session memory — pending_document_results field
    7. Tool handler — find_document_by_context, open_document_result
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Make sure the project root is on the path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════

def _make_temp_txt(content: str, suffix: str = ".txt") -> str:
    """Write content to a temporary file and return its path."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ══════════════════════════════════════════════════════════════════════
# 1. Scanner Tests
# ══════════════════════════════════════════════════════════════════════

class TestScanner:
    """Validate extension filtering and skip-dir logic."""

    def test_supported_extensions_set(self):
        from agentic.document_search.scanner import SUPPORTED_EXTENSIONS
        assert "pdf" in SUPPORTED_EXTENSIONS
        assert "docx" in SUPPORTED_EXTENSIONS
        assert "pptx" in SUPPORTED_EXTENSIONS
        assert "xlsx" in SUPPORTED_EXTENSIONS
        assert "txt" in SUPPORTED_EXTENSIONS
        assert "py" in SUPPORTED_EXTENSIONS
        assert "md" in SUPPORTED_EXTENSIONS

    def test_unsupported_extensions_excluded(self):
        from agentic.document_search.scanner import SUPPORTED_EXTENSIONS
        assert "exe" not in SUPPORTED_EXTENSIONS
        assert "dll" not in SUPPORTED_EXTENSIONS
        assert "jpg" not in SUPPORTED_EXTENSIONS
        assert "mp3" not in SUPPORTED_EXTENSIONS

    def test_should_skip_dir_node_modules(self):
        from agentic.document_search.scanner import _should_skip_dir
        assert _should_skip_dir("C:\\Projects\\my_app", "node_modules") is True

    def test_should_skip_dir_git(self):
        from agentic.document_search.scanner import _should_skip_dir
        assert _should_skip_dir("C:\\Projects\\repo", ".git") is True

    def test_should_skip_dir_hidden(self):
        from agentic.document_search.scanner import _should_skip_dir
        assert _should_skip_dir("C:\\Users\\test", ".cache") is True

    def test_should_not_skip_normal_dir(self):
        from agentic.document_search.scanner import _should_skip_dir
        assert _should_skip_dir("C:\\Users\\test\\Documents", "Projects") is False

    def test_scan_yields_supported_files(self):
        """Create a temp dir with mixed files; only supported ones should appear."""
        from agentic.document_search.scanner import scan_drives, SUPPORTED_EXTENSIONS

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create supported files
            txt_path = os.path.join(tmpdir, "notes.txt")
            pdf_path = os.path.join(tmpdir, "report.pdf")
            # Create unsupported files
            exe_path = os.path.join(tmpdir, "program.exe")
            img_path = os.path.join(tmpdir, "photo.jpg")

            for p in [txt_path, pdf_path, exe_path, img_path]:
                Path(p).write_text("dummy", encoding="utf-8")

            found = list(scan_drives(extra_roots=[tmpdir]))
            found_paths = {f[0] for f in found}

            assert txt_path in found_paths
            assert pdf_path in found_paths
            assert exe_path not in found_paths
            assert img_path not in found_paths


# ══════════════════════════════════════════════════════════════════════
# 2. Cache Tests
# ══════════════════════════════════════════════════════════════════════

class TestCache:
    """Test SQLite cache CRUD operations using a temp DB."""

    @pytest.fixture(autouse=True)
    def temp_db(self, tmp_path, monkeypatch):
        """Redirect DB_PATH to a temp directory for each test."""
        db_path = str(tmp_path / "test_index.db")
        monkeypatch.setattr("agentic.document_search.cache.DB_PATH", db_path)
        # Reset per-thread connection
        import agentic.document_search.cache as cache_mod
        if hasattr(cache_mod._local, "conn"):
            try:
                cache_mod._local.conn.close()
            except Exception:
                pass
            cache_mod._local.conn = None
        cache_mod.init_db()
        yield
        if hasattr(cache_mod._local, "conn"):
            try:
                cache_mod._local.conn.close()
            except Exception:
                pass
            cache_mod._local.conn = None

    def _make_indexed_file(self, path="/tmp/test.txt", filename="test.txt") -> object:
        from agentic.document_search.schemas import IndexedFile
        return IndexedFile(
            path=path,
            filename=filename,
            extension="txt",
            size_bytes=100,
            modified_ts=time.time(),
            folder="tmp",
            folder_path="/tmp",
            sample_text="Hello world test content",
            keywords="hello world test",
            summary="Hello world.",
            embedding_blob=None,
        )

    def test_upsert_and_retrieve(self):
        from agentic.document_search import cache
        f = self._make_indexed_file()
        cache.upsert_file(f)
        retrieved = cache.get_file_by_path(f.path)
        assert retrieved is not None
        assert retrieved.filename == f.filename
        assert retrieved.keywords == f.keywords

    def test_upsert_is_idempotent(self):
        from agentic.document_search import cache
        f = self._make_indexed_file()
        cache.upsert_file(f)
        cache.upsert_file(f)  # second insert should replace cleanly
        count = cache.get_indexed_count()
        assert count == 1

    def test_get_nonexistent_returns_none(self):
        from agentic.document_search import cache
        result = cache.get_file_by_path("/does/not/exist.txt")
        assert result is None

    def test_delete_file(self):
        from agentic.document_search import cache
        f = self._make_indexed_file()
        cache.upsert_file(f)
        assert cache.get_indexed_count() == 1
        cache.delete_file(f.path)
        assert cache.get_indexed_count() == 0

    def test_get_all_files(self):
        from agentic.document_search import cache
        f1 = self._make_indexed_file("/tmp/a.txt", "a.txt")
        f2 = self._make_indexed_file("/tmp/b.txt", "b.txt")
        cache.upsert_file(f1)
        cache.upsert_file(f2)
        all_files = cache.get_all_files(with_embeddings=False)
        assert len(all_files) == 2

    def test_last_scan_time(self):
        from agentic.document_search import cache
        assert cache.get_last_scan_time() == 0.0
        ts = time.time()
        cache.set_last_scan_time(ts)
        assert abs(cache.get_last_scan_time() - ts) < 1.0


# ══════════════════════════════════════════════════════════════════════
# 3. Embeddings / Extractor Tests
# ══════════════════════════════════════════════════════════════════════

class TestEmbeddings:
    """Test text extraction and keyword/summary helpers."""

    def test_extract_text_plain_txt(self):
        from agentic.document_search.embeddings import extract_text
        path = _make_temp_txt("The quick brown fox jumps over the lazy dog.")
        try:
            text = extract_text(path)
            assert "quick" in text
            assert "fox" in text
        finally:
            os.unlink(path)

    def test_extract_text_returns_empty_on_binary(self):
        """Non-text binary files should return empty string, not raise."""
        from agentic.document_search.embeddings import extract_text
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "wb") as f:
            f.write(b"\x00\x01\x02\x03\xff\xfe")  # binary noise
        try:
            text = extract_text(path)
            assert isinstance(text, str)
        finally:
            os.unlink(path)

    def test_extract_keywords(self):
        from agentic.document_search.embeddings import extract_keywords
        text = "The CDOT proposal discusses battery technology and energy storage systems."
        keywords = extract_keywords(text)
        assert "cdot" in keywords or "proposal" in keywords or "battery" in keywords

    def test_extract_summary_short_text(self):
        from agentic.document_search.embeddings import extract_summary
        text = "Short text."
        assert extract_summary(text) == "Short text."

    def test_extract_summary_truncates(self):
        from agentic.document_search.embeddings import extract_summary
        text = "A" * 500
        result = extract_summary(text, max_chars=100)
        assert len(result) <= 105  # small buffer for ellipsis

    def test_cosine_similarity_identical(self):
        import numpy as np
        from agentic.document_search.embeddings import cosine_similarity
        v = np.array([0.5, 0.5, 0.5, 0.5], dtype=np.float32)
        sim = cosine_similarity(v, v)
        assert abs(sim - 1.0) < 1e-5

    def test_cosine_similarity_orthogonal(self):
        import numpy as np
        from agentic.document_search.embeddings import cosine_similarity
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        sim = cosine_similarity(a, b)
        assert abs(sim) < 1e-5

    def test_blob_roundtrip(self):
        import numpy as np
        from agentic.document_search.embeddings import blob_to_vector
        v = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        blob = v.tobytes()
        v2 = blob_to_vector(blob)
        assert v2 is not None
        assert np.allclose(v, v2)


# ══════════════════════════════════════════════════════════════════════
# 4. Ranking Tests
# ══════════════════════════════════════════════════════════════════════

class TestRanking:
    """Test that the ranker orders results correctly."""

    def _make_file(self, path, filename, keywords, summary="", modified_delta=0):
        from agentic.document_search.schemas import IndexedFile
        return IndexedFile(
            path=path,
            filename=filename,
            extension=filename.rsplit(".", 1)[-1] if "." in filename else "txt",
            size_bytes=1000,
            modified_ts=time.time() - modified_delta,
            folder=Path(path).parent.name,
            folder_path=str(Path(path).parent),
            sample_text=keywords,
            keywords=keywords,
            summary=summary,
            embedding_blob=None,  # no embeddings for unit test
        )

    def test_rank_returns_top_n(self):
        from agentic.document_search.ranking import rank_results
        files = [
            self._make_file(f"/docs/file{i}.txt", f"file{i}.txt", f"keyword{i}")
            for i in range(10)
        ]
        results = rank_results("keyword5", files, top_n=5)
        assert len(results) <= 5

    def test_rank_empty_candidates(self):
        from agentic.document_search.ranking import rank_results
        results = rank_results("anything", [], top_n=5)
        assert results == []

    def test_rank_assigns_sequential_ranks(self):
        from agentic.document_search.ranking import rank_results
        files = [
            self._make_file(f"/docs/file{i}.txt", f"file{i}.txt", "common keyword")
            for i in range(3)
        ]
        results = rank_results("common keyword document", files, top_n=3)
        ranks = [r.rank for r in results]
        assert ranks == list(range(1, len(results) + 1))

    def test_high_filename_match_scores_high(self):
        from agentic.document_search.ranking import rank_results
        # The CDOT file should rank above an unrelated file
        cdot_file = self._make_file("/docs/CDOT_Proposal.docx", "CDOT_Proposal.docx",
                                     "cdot proposal battery energy transport")
        other_file = self._make_file("/docs/recipe.docx", "recipe.docx",
                                      "cooking chocolate cake ingredients")
        results = rank_results("CDOT proposal", [cdot_file, other_file], top_n=2)
        assert len(results) >= 1
        assert results[0].filename == "CDOT_Proposal.docx"

    def test_confidence_labels(self):
        from agentic.document_search.ranking import _confidence_label
        assert _confidence_label(0.8) == "high"
        assert _confidence_label(0.5) == "medium"
        assert _confidence_label(0.2) == "low"

    def test_recency_score(self):
        from agentic.document_search.ranking import _recency_score
        # Recent file
        assert _recency_score(time.time() - 60) > 0.99
        # Old file (5 years ago)
        assert _recency_score(time.time() - 5 * 365 * 24 * 3600) == 0.0


# ══════════════════════════════════════════════════════════════════════
# 5. End-to-End Search Test (no real embeddings)
# ══════════════════════════════════════════════════════════════════════

class TestSearch:
    """Integration test for ContextDocumentSearch with a temp DB."""

    @pytest.fixture(autouse=True)
    def temp_db(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "test_search.db")
        monkeypatch.setattr("agentic.document_search.cache.DB_PATH", db_path)
        import agentic.document_search.cache as cache_mod
        if hasattr(cache_mod._local, "conn"):
            try:
                cache_mod._local.conn.close()
            except Exception:
                pass
            cache_mod._local.conn = None
        cache_mod.init_db()
        yield
        if hasattr(cache_mod._local, "conn"):
            try:
                cache_mod._local.conn.close()
            except Exception:
                pass
            cache_mod._local.conn = None

    def test_empty_index_returns_empty(self):
        from agentic.document_search.search import ContextDocumentSearch
        searcher = ContextDocumentSearch()
        results = searcher.search("CDOT proposal")
        assert results == []

    def test_search_returns_results_from_index(self):
        from agentic.document_search import cache
        from agentic.document_search.schemas import IndexedFile
        from agentic.document_search.search import ContextDocumentSearch

        # Seed the cache with a relevant file
        f = IndexedFile(
            path="/docs/CDOT_Proposal.docx",
            filename="CDOT_Proposal.docx",
            extension="docx",
            size_bytes=50000,
            modified_ts=time.time() - 3600,
            folder="docs",
            folder_path="/docs",
            sample_text="CDOT proposal battery project renewable energy transportation",
            keywords="cdot proposal battery project renewable energy transportation",
            summary="CDOT proposal for battery-powered transportation.",
            embedding_blob=None,
        )
        cache.upsert_file(f)

        searcher = ContextDocumentSearch()
        results = searcher.search("CDOT proposal", top_n=5)
        assert len(results) >= 1
        assert results[0].filename == "CDOT_Proposal.docx"

    def test_search_empty_query_returns_empty(self):
        from agentic.document_search.search import ContextDocumentSearch
        searcher = ContextDocumentSearch()
        results = searcher.search("")
        assert results == []


# ══════════════════════════════════════════════════════════════════════
# 6. Session Memory Tests
# ══════════════════════════════════════════════════════════════════════

class TestSessionMemory:
    """Verify the pending_document_results field on SessionState."""

    def test_pending_document_results_default_empty(self):
        from agentic.memory.session_state import SessionState
        session = SessionState.__new__(SessionState)
        session._init_state()
        assert hasattr(session, "pending_document_results")
        assert session.pending_document_results == []

    def test_pending_document_results_stores_list(self):
        from agentic.memory.session_state import get_session
        session = get_session()
        session.pending_document_results = [{"rank": 1, "filename": "test.docx"}]
        assert session.pending_document_results[0]["filename"] == "test.docx"

    def test_clear_all_resets_pending_results(self):
        from agentic.memory.session_state import get_session
        session = get_session()
        session.pending_document_results = [{"rank": 1, "filename": "test.docx"}]
        session.clear_all()
        assert session.pending_document_results == []


# ══════════════════════════════════════════════════════════════════════
# 7. Tool Handler Tests
# ══════════════════════════════════════════════════════════════════════

class TestFindDocumentTool:
    """Test the find_document_by_context tool handler."""

    def test_missing_query_returns_failure(self):
        from automation.document_search_tool import find_document_by_context
        result = find_document_by_context({})
        assert result.success is False
        assert "query" in result.message.lower() or "query" in (result.message or "").lower()

    def test_empty_query_returns_failure(self):
        from automation.document_search_tool import find_document_by_context
        result = find_document_by_context({"query": "   "})
        assert result.success is False

    def test_returns_success_with_mock_results(self):
        """find_document_by_context should succeed when the manager returns results."""
        from automation.document_search_tool import find_document_by_context
        from agentic.document_search.schemas import SearchResult

        mock_results = [
            SearchResult(
                rank=1, score=0.9,
                path="/docs/proposal.docx",
                filename="proposal.docx",
                extension="docx",
                folder="docs",
                modified_ts=time.time(),
                confidence="high",
                snippet="CDOT proposal content.",
            )
        ]

        with patch("agentic.file_context_search.manager.DocumentSearchManager.find_documents",
                   return_value=mock_results):
            with patch("agentic.document_search.manager.DocumentSearchManager.find_documents",
                       return_value=mock_results):
                with patch("agentic.document_search.manager.DocumentSearchManager.start_indexer"):
                    result = find_document_by_context({"query": "CDOT proposal"})

        assert result.success is True
        assert result.output is not None
        if isinstance(result.data, dict) and "results" in result.data:
            parsed = result.data["results"]
        else:
            parsed = json.loads(result.output)
        assert len(parsed) == 1
        assert parsed[0]["filename"] == "proposal.docx"

    def test_empty_results_still_succeeds(self):
        """Even with zero results, the tool should return success=True with an informational message."""
        from automation.document_search_tool import find_document_by_context

        with patch("agentic.document_search.manager.DocumentSearchManager.find_documents",
                   return_value=[]):
            with patch(
                "agentic.document_search.manager.DocumentSearchManager.get_indexer_status",
                return_value={"indexed_count": 100, "is_running": True, "is_ready": True, "last_scan": time.time()}
            ):
                with patch("agentic.document_search.manager.DocumentSearchManager.start_indexer"):
                    result = find_document_by_context({"query": "nonexistent document xyz"})

        assert result.success is True


class TestOpenDocumentResult:
    """Validate opening a previously found result by its 1-based index."""

    def test_no_pending_results_returns_failure(self):
        from automation.document_search_tool import open_document_result
        from agentic.memory.session_state import get_session
        session = get_session()
        session.pending_document_results = []

        result = open_document_result({"result_number": 1})
        assert result.success is False
        assert "search" in result.message.lower() or "find" in result.message.lower()

    def test_invalid_number_returns_failure(self):
        from automation.document_search_tool import open_document_result
        from agentic.memory.session_state import get_session

        session = get_session()
        session.pending_document_results = [{"rank": 1, "path": "/docs/a.docx", "filename": "a.docx"}]

        result = open_document_result({"result_number": 99})
        assert result.success is False
        assert "invalid" in result.message.lower() or "1" in result.message

    def test_opens_correct_file(self):
        from automation.document_search_tool import open_document_result
        from agentic.memory.session_state import get_session

        session = get_session()
        session.pending_document_results = [
            {"rank": 1, "path": "/docs/report.pdf", "filename": "report.pdf"},
            {"rank": 2, "path": "/docs/proposal.docx", "filename": "proposal.docx"},
        ]

        with patch("os.path.exists", return_value=True):
            with patch("agentic.document_retrieval.manager.DocumentRetrievalManager.open_result", return_value=True) as mock_open:
                result = open_document_result({"result_number": 2, "confirmed": True})

        assert result.success is True
        mock_open.assert_called_once_with("/docs/proposal.docx")


    def test_ordinal_word_mapping(self):
        """Verify that string numbers like '2' are parsed correctly."""
        from automation.document_search_tool import open_document_result
        from agentic.memory.session_state import get_session
        from execution.schemas import ExecutionResult

        session = get_session()
        session.pending_document_results = [
            {"rank": 1, "path": "/docs/a.docx", "filename": "a.docx"},
            {"rank": 2, "path": "/docs/b.pdf", "filename": "b.pdf"},
        ]

        mock_result = ExecutionResult(success=True, tool="open_file", message="Opened.")
        with patch("automation.filesystem.open_file", return_value=mock_result):
            result = open_document_result({"result_number": "1"})

        assert result.success is True


# ══════════════════════════════════════════════════════════════════════
# 8. Preview Tests
# ══════════════════════════════════════════════════════════════════════

class TestPreview:
    """Test the format helpers in preview.py."""

    def test_format_results_for_voice_empty(self):
        from agentic.document_search.preview import format_results_for_voice
        msg = format_results_for_voice([])
        assert "could not find" in msg.lower() or "no matching" in msg.lower()

    def test_format_results_for_voice_with_results(self):
        from agentic.document_search.schemas import SearchResult
        from agentic.document_search.preview import format_results_for_voice

        results = [
            SearchResult(
                rank=1, score=0.8,
                path="/docs/a.docx",
                filename="a.docx",
                extension="docx",
                folder="docs",
                modified_ts=time.time(),
                confidence="high",
                snippet="Content here.",
            )
        ]
        msg = format_results_for_voice(results)
        assert "1" in msg
        assert "a.docx" in msg
        assert "open number" in msg.lower() or "open" in msg.lower()

    def test_format_results_for_display(self):
        from agentic.document_search.schemas import SearchResult
        from agentic.document_search.preview import format_results_for_display

        results = [
            SearchResult(
                rank=1, score=0.9,
                path="/docs/b.pdf",
                filename="b.pdf",
                extension="pdf",
                folder="docs",
                modified_ts=time.time(),
                confidence="high",
                snippet="PDF content.",
            )
        ]
        display = format_results_for_display(results)
        assert len(display) == 1
        assert display[0]["filename"] == "b.pdf"
        assert "rank" in display[0]
        assert "confidence" in display[0]
