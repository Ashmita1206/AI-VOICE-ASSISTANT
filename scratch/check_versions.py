import sys
print("Python:", sys.version, flush=True)

mods = [
    ("faster_whisper", "faster-whisper"),
    ("ctranslate2", "ctranslate2"),
    ("sentence_transformers", "sentence-transformers"),
    ("rank_bm25", "rank-bm25"),
    ("faiss", "faiss"),
    ("flask", "flask"),
    ("sounddevice", "sounddevice"),
    ("edge_tts", "edge-tts"),
    ("pyttsx3", "pyttsx3"),
    ("playwright", "playwright"),
    ("pyautogui", "pyautogui"),
    ("win32gui", "pywin32"),
    ("pyrogram", "pyrogram"),
    ("sqlalchemy", "sqlalchemy"),
    ("pydantic", "pydantic"),
    ("psutil", "psutil"),
    ("fitz", "PyMuPDF"),
    ("docx", "python-docx"),
    ("pptx", "python-pptx"),
    ("openpyxl", "openpyxl"),
    ("pandas", "pandas")
]

for mod_name, disp_name in mods:
    try:
        m = __import__(mod_name)
        v = getattr(m, "__version__", "installed")
        print(f"{disp_name}: {v}", flush=True)
    except Exception as e:
        print(f"{disp_name}: NOT_INSTALLED ({e})", flush=True)
