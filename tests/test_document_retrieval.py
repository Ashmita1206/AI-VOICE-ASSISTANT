"""
Unit tests for Production-Grade Document Scanning, Query Parsing & Hybrid Ranking Engine
"""

import pytest
import os
import time
from agentic.document_retrieval.retriever import normalize_query, extract_extension_preference, parse_query
from agentic.document_retrieval.ranking import rank_documents
from agentic.document_retrieval.schemas import IndexedDocument
from agentic.document_retrieval.utils import generate_summary
from agentic.document_retrieval import config, scanner

def test_query_normalization():
    raw_query = "Open data science document"
    normalized = normalize_query(raw_query)
    assert normalized == "data science"
    
    raw_query_2 = "Please find the Flipkart report file"
    normalized_2 = normalize_query(raw_query_2)
    assert normalized_2 == "flipkart report"

def test_parse_query_entities():
    parsed = parse_query("Open HealthSphere presentation")
    assert parsed.intent == "open"
    assert parsed.doc_type == "presentation"
    assert "healthsphere" in parsed.target_filename_tokens
    assert "pptx" in parsed.preferred_extensions or "ppt" in parsed.preferred_extensions

def test_system_and_python_exclusions():
    # Verify system/environment folders are in SKIP_DIR_NAMES
    assert "site-packages" in config.SKIP_DIR_NAMES
    assert "node_modules" in config.SKIP_DIR_NAMES
    assert "python310" in config.SKIP_DIR_NAMES
    assert "anaconda3" in config.SKIP_DIR_NAMES
    assert "jdk" in config.SKIP_DIR_NAMES
    assert "appdata" in config.SKIP_DIR_NAMES
    assert "json" in config.HIGH_PRIORITY_DOC_EXTENSIONS

def test_hybrid_ranking_filename_dominance():
    query = "Open Data Science document"
    doc1 = IndexedDocument(
        id=1, path="C:\\Users\\User\\Documents\\DataScience.pdf", filename="DataScience.pdf",
        folder="Documents", extension="pdf", size_bytes=1000, modified_ts=time.time(),
        summary="Data Science & ML Reference Notes", entities_json="{}", keywords="data science notes python ml",
        content_hash="abc1", last_indexed=time.time()
    )
    # Python stdlib doc file (simulated candidate)
    doc2 = IndexedDocument(
        id=2, path="C:\\Python310\\Lib\\site-packages\\docs\\sys_path_init.html", filename="sys_path_init.html",
        folder="docs", extension="html", size_bytes=5000, modified_ts=time.time() - 10000,
        summary="Python system path initialization details.", entities_json="{}", keywords="python sys path init",
        content_hash="xyz2", last_indexed=time.time()
    )
    
    candidates = [doc2, doc1]
    distances = [0.8, 0.4]  # doc2 has higher semantic embedding distance, but doc1 MUST win
    
    results = rank_documents(query, candidates, distances, top_n=2)
    assert len(results) >= 1
    assert results[0].filename == "DataScience.pdf"

def test_deduplication():
    query = "HealthSphere"
    now = time.time()
    doc1 = IndexedDocument(
        id=1, path="C:\\Users\\User\\Documents\\HealthSphere.pdf", filename="HealthSphere.pdf",
        folder="Documents", extension="pdf", size_bytes=1000, modified_ts=now,
        summary="Healthcare AI proposal document.", entities_json="{}", keywords="healthsphere healthcare report",
        content_hash="hash1", last_indexed=now
    )
    doc2 = IndexedDocument(
        id=2, path="C:\\Users\\User\\Downloads\\HealthSphere (1).pdf", filename="HealthSphere (1).pdf",
        folder="Downloads", extension="pdf", size_bytes=1000, modified_ts=now - 5000,
        summary="Healthcare AI proposal document copy.", entities_json="{}", keywords="healthsphere healthcare report",
        content_hash="hash1", last_indexed=now
    )
    
    candidates = [doc2, doc1]
    distances = [0.6, 0.6]
    
    results = rank_documents(query, candidates, distances, top_n=2)
    # Deduplication should keep 1 top result
    assert len(results) == 1
    assert results[0].filename == "HealthSphere.pdf"

def test_html_markup_stripping_in_preview():
    html_text = "<!DOCTYPE html><html><head><style>body { color: red; }</style></head><body><h1>Data Science Notes</h1><p>Deep Learning and Neural Networks.</p></body></html>"
    summary = generate_summary(html_text)
    assert "<!DOCTYPE" not in summary
    assert "<style>" not in summary
    assert "Data Science Notes Deep Learning and Neural Networks." in summary

def test_folder_variant_normalization():
    from agentic.document_retrieval.retriever import normalize_folder_name
    assert normalize_folder_name("money mentor") == "moneymentor"
    assert normalize_folder_name("Money Mentor") == "moneymentor"
    assert normalize_folder_name("moneymentor") == "moneymentor"
    assert normalize_folder_name("MoneyMentor") == "moneymentor"
    assert normalize_folder_name("money_mentor") == "moneymentor"
    assert normalize_folder_name("money-mentor") == "moneymentor"

def test_recursive_folder_search_isolation(monkeypatch, tmp_path):
    import numpy as np
    from agentic.document_retrieval import config, metadata, search, embeddings, cache
    temp_db = str(tmp_path / "test_doc_retrieval.db")
    monkeypatch.setattr(config, "SQLITE_DB_PATH", temp_db)
    monkeypatch.setattr(embeddings, "generate_embedding", lambda txt: np.zeros(384, dtype=np.float32))
    monkeypatch.setattr(cache, "_get_faiss_index", lambda: None)
    monkeypatch.setattr(cache, "search", lambda vec, top_n=50: ([], []))
    monkeypatch.setattr(os.path, "exists", lambda p: True)
    if hasattr(metadata._local, "conn"):
        metadata._local.conn = None
        
    metadata.init_db()
    now = time.time()
    
    # 1. Money Mentor files in D:\moneymentor\
    money_doc1 = IndexedDocument(
        id=101, path="D:\\moneymentor\\BusinessPlan.pdf", filename="BusinessPlan.pdf",
        folder="moneymentor", parent_folder="moneymentor", project_folder="moneymentor",
        relative_path="BusinessPlan.pdf", extension="pdf", size_bytes=1000, modified_ts=now,
        summary="Money Mentor Business Plan", entities_json="{}", keywords="money mentor business plan",
        content_hash="m1", last_indexed=now
    )
    money_doc2 = IndexedDocument(
        id=102, path="D:\\moneymentor\\PitchDeck.pptx", filename="PitchDeck.pptx",
        folder="moneymentor", parent_folder="moneymentor", project_folder="moneymentor",
        relative_path="PitchDeck.pptx", extension="pptx", size_bytes=2000, modified_ts=now,
        summary="Money Mentor Pitch Deck", entities_json="{}", keywords="money mentor pitch deck",
        content_hash="m2", last_indexed=now
    )
    
    # 2. Unrelated files in global index
    unrelated1 = IndexedDocument(
        id=201, path="C:\\HealthSphere\\HealthSphere.pdf", filename="HealthSphere.pdf",
        folder="HealthSphere", parent_folder="HealthSphere", project_folder="HealthSphere",
        relative_path="HealthSphere.pdf", extension="pdf", size_bytes=1500, modified_ts=now,
        summary="HealthSphere Healthcare", entities_json="{}", keywords="healthsphere healthcare",
        content_hash="u1", last_indexed=now
    )
    unrelated2 = IndexedDocument(
        id=202, path="C:\\MSYS\\MSYS_LICENSE.rtf", filename="MSYS_LICENSE.rtf",
        folder="MSYS", parent_folder="MSYS", project_folder="MSYS",
        relative_path="MSYS_LICENSE.rtf", extension="rtf", size_bytes=500, modified_ts=now,
        summary="MSYS License", entities_json="{}", keywords="license msys",
        content_hash="u2", last_indexed=now
    )
    unrelated3 = IndexedDocument(
        id=203, path="C:\\Code\\Feature Selection.ipynb", filename="Feature Selection.ipynb",
        folder="Code", parent_folder="Code", project_folder="Code",
        relative_path="Feature Selection.ipynb", extension="ipynb", size_bytes=3000, modified_ts=now,
        summary="Feature selection notebook", entities_json="{}", keywords="feature selection python",
        content_hash="u3", last_indexed=now
    )
    unrelated4 = IndexedDocument(
        id=204, path="C:\\Python\\Lib\\index.js", filename="index.js",
        folder="Lib", parent_folder="Lib", project_folder="Python",
        relative_path="Lib\\index.js", extension="js", size_bytes=400, modified_ts=now,
        summary="JS file", entities_json="{}", keywords="index js",
        content_hash="u4", last_indexed=now
    )
    
    # Other project files for Stage 7 queries
    hs_pres = IndexedDocument(
        id=301, path="C:\\Projects\\HealthSphere\\Presentation.pptx", filename="Presentation.pptx",
        folder="HealthSphere", parent_folder="HealthSphere", project_folder="HealthSphere",
        relative_path="Presentation.pptx", extension="pptx", size_bytes=2500, modified_ts=now,
        summary="HealthSphere Presentation", entities_json="{}", keywords="healthsphere presentation slides",
        content_hash="hs1", last_indexed=now
    )
    vg_rep = IndexedDocument(
        id=302, path="C:\\Projects\\VoltGuard\\VoltGuard_Report.pdf", filename="VoltGuard_Report.pdf",
        folder="VoltGuard", parent_folder="VoltGuard", project_folder="VoltGuard",
        relative_path="VoltGuard_Report.pdf", extension="pdf", size_bytes=1800, modified_ts=now,
        summary="VoltGuard Battery Report", entities_json="{}", keywords="voltguard battery report",
        content_hash="vg1", last_indexed=now
    )
    dsmp_nb = IndexedDocument(
        id=303, path="C:\\Projects\\DSMP\\DSMP_Analysis.ipynb", filename="DSMP_Analysis.ipynb",
        folder="DSMP", parent_folder="DSMP", project_folder="DSMP",
        relative_path="DSMP_Analysis.ipynb", extension="ipynb", size_bytes=4000, modified_ts=now,
        summary="DSMP Data Science Notebook", entities_json="{}", keywords="dsmp notebook data science",
        content_hash="ds1", last_indexed=now
    )
    rag_doc = IndexedDocument(
        id=304, path="C:\\Projects\\RAG\\RAG_Architecture.pdf", filename="RAG_Architecture.pdf",
        folder="RAG", parent_folder="RAG", project_folder="RAG",
        relative_path="RAG_Architecture.pdf", extension="pdf", size_bytes=3200, modified_ts=now,
        summary="RAG Architecture Paper", entities_json="{}", keywords="rag document retrieval architecture",
        content_hash="rag1", last_indexed=now
    )
    
    # Upsert all test documents into SQLite
    for doc in [money_doc1, money_doc2, unrelated1, unrelated2, unrelated3, unrelated4, hs_pres, vg_rep, dsmp_nb, rag_doc]:
        metadata.upsert_document(doc)
        
    # Verify Query 1: Open Money Mentor document
    res_mm = search.search_documents("Open Money Mentor document from File Explorer", top_n=5)
    filenames_mm = [r.filename for r in res_mm]
    assert "BusinessPlan.pdf" in filenames_mm or "PitchDeck.pptx" in filenames_mm
    assert "MSYS_LICENSE.rtf" not in filenames_mm
    assert "Feature Selection.ipynb" not in filenames_mm
    assert "index.js" not in filenames_mm

    # Verify Query 2: Open HealthSphere presentation
    res_hs = search.search_documents("Open HealthSphere presentation", top_n=5)
    filenames_hs = [r.filename for r in res_hs]
    assert any("HealthSphere" in fn or fn == "Presentation.pptx" for fn in filenames_hs)

    # Verify Query 3: Open VoltGuard report
    res_vg = search.search_documents("Open VoltGuard report", top_n=5)
    filenames_vg = [r.filename for r in res_vg]
    assert "VoltGuard_Report.pdf" in filenames_vg

    # Verify Query 4: Find DSMP notebook
    res_ds = search.search_documents("Find DSMP notebook", top_n=5)
    filenames_ds = [r.filename for r in res_ds]
    assert "DSMP_Analysis.ipynb" in filenames_ds

    # Verify Query 5: Open RAG document
    res_rag = search.search_documents("Open RAG document", top_n=5)
    filenames_rag = [r.filename for r in res_rag]
    assert "RAG_Architecture.pdf" in filenames_rag

def test_real_filesystem_validation_and_stale_purging(monkeypatch, tmp_path):
    """Verify Phase 2, 3, 4, 8 & 12: Real physical files are discovered, stale/deleted files purged."""
    import numpy as np
    from agentic.document_retrieval import config, metadata, search, indexer, embeddings, cache
    
    temp_db = str(tmp_path / "test_consistency.db")
    monkeypatch.setattr(config, "SQLITE_DB_PATH", temp_db)
    monkeypatch.setattr(embeddings, "generate_embedding", lambda txt: np.zeros(384, dtype=np.float32))
    monkeypatch.setattr(embeddings, "generate_embeddings_batch", lambda txts: [np.zeros(384, dtype=np.float32) for _ in txts])
    monkeypatch.setattr(cache, "_get_faiss_index", lambda: None)
    monkeypatch.setattr(cache, "search", lambda vec, top_n=50: ([], []))
    
    if hasattr(metadata._local, "conn"):
        metadata._local.conn = None
        
    metadata.init_db()
    
    # 1. Create real physical directory and files on disk
    mm_dir = tmp_path / "moneymentor"
    mm_dir.mkdir(parents=True, exist_ok=True)
    
    real_f1 = mm_dir / "BusinessPlan.pdf"
    real_f1.write_text("Money Mentor Business Plan Content")
    
    real_f2 = mm_dir / "README.pdf"
    real_f2.write_text("Money Mentor README Documentation")
    
    real_f3 = mm_dir / "Financials.xlsx"
    real_f3.write_text("Money Mentor Financial Breakdown")
    
    real_f4 = mm_dir / "Architecture.png"
    real_f4.write_text("Money Mentor Architecture Diagram")
    
    # 2. Insert stale doc PitchDeck.pptx into SQLite (does NOT exist on disk)
    stale_path = str(mm_dir / "PitchDeck.pptx")
    stale_doc = IndexedDocument(
        id=999, path=stale_path, filename="PitchDeck.pptx",
        folder="moneymentor", parent_folder="moneymentor", project_folder="moneymentor",
        relative_path="PitchDeck.pptx", extension="pptx", size_bytes=5000, modified_ts=time.time() - 1000,
        summary="Stale pitch deck copy", entities_json="{}", keywords="pitchdeck moneymentor",
        content_hash="stale999", last_indexed=time.time()
    )
    metadata.upsert_document(stale_doc)
    
    # Verify stale doc is initially in SQLite
    assert metadata.get_document_by_path(stale_path) is not None
    
    # 3. Perform indexing scan & consistency check
    idxer = indexer.DocumentIndexer()
    # Scan mock drive root
    monkeypatch.setattr(scanner, "_get_user_priority_roots", lambda: [str(mm_dir)])
    monkeypatch.setattr(scanner, "_get_drives", lambda: [])
    
    idxer._perform_scan()
    
    # Stale PitchDeck.pptx must have been purged from SQLite
    assert metadata.get_document_by_path(stale_path) is None
    
    # All 4 physical files must exist in SQLite
    assert metadata.get_document_by_path(str(real_f1)) is not None
    assert metadata.get_document_by_path(str(real_f2)) is not None
    assert metadata.get_document_by_path(str(real_f3)) is not None
    assert metadata.get_document_by_path(str(real_f4)) is not None
    
    # 4. Perform search query and verify returned results
    results = search.search_documents("Open Money Mentor document from File Explorer", top_n=10)
    returned_filenames = [r.filename for r in results]
    
    # Non-existent PitchDeck.pptx MUST NOT appear
    assert "PitchDeck.pptx" not in returned_filenames
    
    # All physical files in moneymentor must be returned
    assert "BusinessPlan.pdf" in returned_filenames
    assert "README.pdf" in returned_filenames
    assert "Financials.xlsx" in returned_filenames
    assert "Architecture.png" in returned_filenames

def test_debug_index_api(monkeypatch, tmp_path):
    """Verify Phase 11 Debug API functionality."""
    import numpy as np
    from agentic.document_retrieval import config, metadata, indexer, embeddings, cache
    
    temp_db = str(tmp_path / "test_debug_api.db")
    monkeypatch.setattr(config, "SQLITE_DB_PATH", temp_db)
    monkeypatch.setattr(embeddings, "generate_embedding", lambda txt: np.zeros(384, dtype=np.float32))
    monkeypatch.setattr(cache, "_get_faiss_index", lambda: None)
    
    if hasattr(metadata._local, "conn"):
        metadata._local.conn = None
        
    metadata.init_db()
    
    mm_dir = tmp_path / "moneymentor"
    mm_dir.mkdir(parents=True, exist_ok=True)
    (mm_dir / "BusinessPlan.pdf").write_text("content")
    (mm_dir / "README.pdf").write_text("content")
    
    idxer = indexer.DocumentIndexer()
    audit_res = idxer.debug_index(str(mm_dir))
    
    assert audit_res["folder"] == str(mm_dir)
    assert "BusinessPlan.pdf" in audit_res["files_found"]
    assert "README.pdf" in audit_res["files_found"]


def test_document_open_permission_layer(monkeypatch, tmp_path):
    """Verify Permission Layer before opening documents: confirmation required before launching file."""
    from automation.document_retrieval_tool import find_document_by_context
    from agentic.memory.session_state import get_session

    session = get_session()
    test_pdf = tmp_path / "HealthSphere_Architecture.pdf"
    test_pdf.write_text("Dummy HealthSphere PDF content")

    session.pending_document_results = [
        {
            "rank": 1,
            "filename": "HealthSphere_Architecture.pdf",
            "path": str(test_pdf),
            "extension": "pdf",
            "folder": "healthsphere"
        }
    ]

    # Stage 1: Call find_document_by_context with result_number=1 WITHOUT confirmation
    res_unconfirmed = find_document_by_context({"result_number": 1})
    assert res_unconfirmed.success is True
    assert res_unconfirmed.requires_interaction is True
    assert res_unconfirmed.data["action"] == "open_permission_required"
    assert res_unconfirmed.data["filename"] == "HealthSphere_Architecture.pdf"
    assert "You are about to open:" in res_unconfirmed.output

    # Stage 2: Call find_document_by_context with result_number=1 WITH confirmation
    res_confirmed = find_document_by_context({"result_number": 1, "confirmed": True})
    assert res_confirmed.success is True
    assert res_confirmed.data.get("opened") is True
    assert "opened" in res_confirmed.output.lower()


def test_single_result_returns_structured_data(monkeypatch, tmp_path):
    """Verify that a single search result returns structured data for frontend modal."""
    from automation.document_retrieval_tool import find_document_by_context
    from agentic.memory.session_state import get_session
    from agentic.file_context_search.manager import DocumentSearchManager
    from agentic.file_context_search.preview import format_results_for_display

    session = get_session()
    test_pdf = tmp_path / "SingleResult.pdf"
    test_pdf.write_text("Single result content")

    # Mock DocumentSearchManager.find_documents to return one result
    class MockSearchResult:
        def __init__(self, path, filename):
            self.rank = 1
            self.score = 0.9
            self.path = path
            self.filename = filename
            self.extension = "pdf"
            self.folder = str(tmp_path)
            self.modified_ts = 0.0
            self.confidence = "high"
            self.snippet = "test snippet"

        def to_dict(self):
            return {
                "rank": self.rank,
                "score": self.score,
                "path": self.path,
                "filename": self.filename,
                "extension": self.extension,
                "folder": self.folder,
                "modified_date": "unknown",
                "confidence": self.confidence,
                "snippet": self.snippet,
            }

        def voice_label(self):
            return f"{self.filename} ({self.extension.upper()})"

    original_find = DocumentSearchManager.find_documents
    DocumentSearchManager.find_documents = lambda q, top_n: [MockSearchResult(str(test_pdf), "SingleResult.pdf")]

    try:
        res = find_document_by_context({"query": "test document"})
        assert res.success is True
        assert res.requires_interaction is False  # Execution completes so frontend can detect results
        assert res.data["action"] == "document_search_results"
        assert "results" in res.data
        assert len(res.data["results"]) == 1
        assert res.data["results"][0]["filename"] == "SingleResult.pdf"
        assert res.data["query"] == "test document"
    finally:
        DocumentSearchManager.find_documents = original_find


def test_multiple_results_require_selection(monkeypatch, tmp_path):
    """Verify that multiple search results return structured data for frontend modal."""
    from automation.document_retrieval_tool import find_document_by_context
    from agentic.memory.session_state import get_session
    from agentic.file_context_search.manager import DocumentSearchManager

    session = get_session()

    # Mock DocumentSearchManager.find_documents to return multiple results
    class MockSearchResult:
        def __init__(self, path, filename, rank):
            self.rank = rank
            self.score = 0.9
            self.path = path
            self.filename = filename
            self.extension = "pdf"
            self.folder = str(tmp_path)
            self.modified_ts = 0.0
            self.confidence = "high"
            self.snippet = "test snippet"

        def to_dict(self):
            return {
                "rank": self.rank,
                "score": self.score,
                "path": self.path,
                "filename": self.filename,
                "extension": self.extension,
                "folder": self.folder,
                "modified_date": "unknown",
                "confidence": self.confidence,
                "snippet": self.snippet,
            }

        def voice_label(self):
            return f"{self.filename} ({self.extension.upper()})"

    pdf1 = tmp_path / "Result1.pdf"
    pdf2 = tmp_path / "Result2.pdf"
    pdf1.write_text("Content 1")
    pdf2.write_text("Content 2")

    original_find = DocumentSearchManager.find_documents
    DocumentSearchManager.find_documents = lambda q, top_n: [
        MockSearchResult(str(pdf1), "Result1.pdf", 1),
        MockSearchResult(str(pdf2), "Result2.pdf", 2)
    ]

    try:
        res = find_document_by_context({"query": "test document"})
        assert res.success is True
        assert res.requires_interaction is False  # Execution completes so frontend can detect results
        assert res.data["action"] == "document_search_results"
        assert len(res.data["results"]) == 2
        assert res.data["query"] == "test document"
    finally:
        DocumentSearchManager.find_documents = original_find


def test_new_search_clears_stale_results(monkeypatch, tmp_path):
    """Verify that a new search replaces previous results in session."""
    from automation.document_retrieval_tool import find_document_by_context
    from agentic.memory.session_state import get_session
    from agentic.file_context_search.manager import DocumentSearchManager

    session = get_session()

    # Set up initial stale results
    session.pending_document_results = [
        {"rank": 1, "filename": "OldResult.pdf", "path": "old/path.pdf"}
    ]
    session.last_document_query = "old query"

    class MockSearchResult:
        def __init__(self, path, filename):
            self.rank = 1
            self.score = 0.9
            self.path = path
            self.filename = filename
            self.extension = "pdf"
            self.folder = str(tmp_path)
            self.modified_ts = 0.0
            self.confidence = "high"
            self.snippet = "test snippet"

        def to_dict(self):
            return {
                "rank": self.rank,
                "score": self.score,
                "path": self.path,
                "filename": self.filename,
                "extension": self.extension,
                "folder": self.folder,
                "modified_date": "unknown",
                "confidence": self.confidence,
                "snippet": self.snippet,
            }

        def voice_label(self):
            return f"{self.filename} ({self.extension.upper()})"

    new_pdf = tmp_path / "NewResult.pdf"
    new_pdf.write_text("New content")

    original_find = DocumentSearchManager.find_documents
    DocumentSearchManager.find_documents = lambda q, top_n: [MockSearchResult(str(new_pdf), "NewResult.pdf")]

    try:
        res = find_document_by_context({"query": "new query"})
        assert res.success is True
        # Verify session was updated with new results
        assert len(session.pending_document_results) == 1
        assert session.pending_document_results[0]["filename"] == "NewResult.pdf"
        assert session.last_document_query == "new query"
        # Old result should be gone
        assert not any(r["filename"] == "OldResult.pdf" for r in session.pending_document_results)
    finally:
        DocumentSearchManager.find_documents = original_find
