"""
Local Heuristic Fallback
========================

Provides rule-based plan generation when the remote LLM is offline.
Maps compound desktop queries to fine-grained sequential steps.
"""

import re
from agentic.llm.schemas import PlannerOutput, PlannerStep

def apply_heuristic_fallback(transcription: str) -> PlannerOutput:
    """Parse transcription with heuristics to generate an offline plan."""
    text = transcription.lower().strip()
    
    from agentic.memory.session_state import get_session
    session = get_session()
    
    # Rule 0.1: Explicit App Launching (prefer desktop applications over web bookmarks)
    if text in ("open calculator", "calculator", "launch calculator", "start calculator", "calc"):
        return PlannerOutput(
            intent="launch_application",
            confidence=0.95,
            reasoning="Matched Calculator application launch.",
            steps=[PlannerStep(tool="launch_application", args={"application": "Calculator"})]
        )

    if text in ("open file explorer", "file explorer", "launch file explorer", "open explorer", "explorer"):
        return PlannerOutput(
            intent="launch_application",
            confidence=0.95,
            reasoning="Matched File Explorer application launch.",
            steps=[PlannerStep(tool="launch_application", args={"application": "File Explorer"})]
        )

    if text in ("open chrome", "chrome", "launch chrome", "google chrome"):
        return PlannerOutput(
            intent="launch_application",
            confidence=0.95,
            reasoning="Matched Google Chrome application launch.",
            steps=[PlannerStep(tool="launch_application", args={"application": "Chrome"})]
        )

    if text in ("open telegram", "telegram", "launch telegram", "start telegram", "check telegram", "telegram open", "open telegram desktop", "telegram desktop", "telegram kholo", "telegram open karo", "telegram open kar do"):
        return PlannerOutput(
            intent="open_application",
            confidence=0.95,
            reasoning="Matched Telegram desktop application launch.",
            steps=[PlannerStep(tool="open_application", args={"application": "telegram"}, description="Open Telegram")]
        )

    if text in ("open gmail", "gmail", "check gmail", "check my gmail", "open my gmail", "launch gmail", "gmail open", "open my mail"):
        return PlannerOutput(
            intent="open_gmail",
            confidence=0.95,
            reasoning="Matched Gmail application pipeline tool.",
            steps=[PlannerStep(tool="open_gmail", args={})]
        )

    if text in ("open spotify", "spotify", "launch spotify", "start spotify", "check spotify", "spotify open"):
        return PlannerOutput(
            intent="open_spotify",
            confidence=0.95,
            reasoning="Matched Spotify application pipeline tool.",
            steps=[PlannerStep(tool="open_spotify", args={})]
        )

    # Rule 0.2: Browser Web Search (Evaluated before local document search)
    if "open" in text and "browser" in text and "search" in text:
        query_match = re.search(r"search\s+(.*)", text)
        query = query_match.group(1).strip() if query_match else ""
        query = re.sub(r"[.!?]+$", "", query).strip()
        return PlannerOutput(
            intent="search_web",
            confidence=0.8,
            reasoning="Matched browser search.",
            steps=[
                PlannerStep(tool="launch_application", args={"application": "chrome"}, wait_for="ui_ready", timeout=60),
                PlannerStep(tool="search_inside_application", args={"query": query})
            ]
        )

    if (text.startswith("search ") or text.startswith("google ") or text.startswith("find information about ") or text.startswith("look up ")) and not re.search(r"\b(my pdf|my document|my file|python file|notebooks|requirements\.txt|whatsapp|on whatsapp)\b", text, re.IGNORECASE):

        query_text = text
        query_text = re.sub(r"^(?:search\s+google\s+for|search\s+for|search\s+web\s+for|search|google|find\s+information\s+about|look\s+up)\s+", "", query_text, flags=re.IGNORECASE)
        query_text = re.sub(r"[.!?]+$", "", query_text).strip() or text
        return PlannerOutput(
            intent="search_web",
            confidence=0.95,
            reasoning=f"Matched browser search query: '{query_text}'",
            steps=[PlannerStep(tool="search_web", args={"query": query_text})]
        )

    # Rule 0.3: File Explorer Context Search (Must NOT capture explicit app launch commands)
    clean_text = re.sub(r"[.!?]+$", "", text.strip())
    known_app_patterns = r"\b(microsoft\s+word|word|microsoft\s+powerpoint|powerpoint|ppt|microsoft\s+excel|excel|microsoft\s+store|store|ubuntu|ubuntu\s+terminal|vs\s+code|visual\s+studio\s+code|calculator|notepad|file\s+explorer)\b"
    if re.search(r"^(?:open|launch|start)\s+(?:microsoft\s+word|word|microsoft\s+powerpoint|powerpoint|ppt|microsoft\s+excel|excel|microsoft\s+store|store|ubuntu|ubuntu\s+terminal|vs\s+code|visual\s+studio\s+code|calculator|notepad|file\s+explorer)$", clean_text, flags=re.IGNORECASE):
        app_name = clean_text.split(" ", 1)[1].strip()
        return PlannerOutput(
            intent="launch_application",
            confidence=0.95,
            reasoning=f"Matched application launch command for '{app_name}'.",
            steps=[PlannerStep(tool="resolve_and_open", args={"query": app_name})]
        )

    find_verbs = r"(find|search|locate|look\s+for|open|where\s+is|need|show\s+me)"
    doc_nouns = r"(file(?!\s*manager)|document|report|proposal|presentation|pdf|ppt|word|excel|spreadsheet|invoice|notes?(?!pad)|notebook(?!s)|deck)"
    if re.search(find_verbs, clean_text, flags=re.IGNORECASE) and re.search(doc_nouns, clean_text, flags=re.IGNORECASE):
        negative_words = r"\b(notepad|open\s+notes|create\s+file|edit\s+txt|write|type|file\s+explorer|explorer)\b"
        is_explicit_app_command = bool(re.search(r"^(?:open|launch|start)\s+" + known_app_patterns + r"$", clean_text, flags=re.IGNORECASE))
        if not re.search(negative_words, clean_text, flags=re.IGNORECASE) and not is_explicit_app_command:
            query_text = text
            query_text = re.sub(rf"^(?:can\s+you\s+)?{find_verbs}\s+(?:the\s+|my\s+|a\s+)?{doc_nouns}(?:s)?\s+(?:about\s+|on\s+|for\s+)?", "", query_text)
            query_text = re.sub(rf"^(?:can\s+you\s+)?{find_verbs}\s+(?:the\s+|my\s+|a\s+)?", "", query_text)
            
            return PlannerOutput(
                intent="find_document_by_context",
                confidence=0.95,
                reasoning="Matched explicit File Explorer Context Search pattern.",
                steps=[PlannerStep(tool="find_document_by_context", args={"query": query_text.strip() or text})]
            )

    # Rule 1: Get active window
    if text in ("get active window", "check active window", "what is the active window", "what app is open", "what app is active"):
        return PlannerOutput(
            intent="check_status",
            confidence=0.9,
            reasoning="Matched active window check.",
            steps=[PlannerStep(tool="get_active_window", args={})]
        )
        
    # Rule 2: Check if app is running
    is_running_match = re.match(r"(?:check\s+if\s+)?(?:is\s+)?(\w+)\s+running", text)
    if is_running_match:
        app = is_running_match.group(1).strip()
        return PlannerOutput(
            intent="check_status",
            confidence=0.9,
            reasoning=f"Matched is app running check for '{app}'.",
            steps=[PlannerStep(tool="is_app_running", args={"app": app})]
        )
        
    # Rule 3: Focus/activate window
    activate_match = re.match(r"(?:focus|activate\s+window|bring\s+to\s+foreground)\s+(.+)", text)
    if activate_match:
        app = activate_match.group(1).strip()
        app = re.sub(r"\s+app$", "", app)
        return PlannerOutput(
            intent="focus_window",
            confidence=0.9,
            reasoning=f"Matched focus window for '{app}'.",
            steps=[PlannerStep(tool="focus_window", args={"target": app})]
        )

    # Rule 4: WhatsApp automation (decomposed)
    whatsapp_match = re.match(r"search\s+(?:for\s+)?(\w+)\s+and\s+write\s+(.+?)(?:\s+on\s+whatsapp)?$", text)
    if not whatsapp_match:
        whatsapp_match = re.match(r"write\s+(.+?)\s+to\s+(\w+)(?:\s+on\s+whatsapp)?$", text)
    if not whatsapp_match:
        whatsapp_match = re.match(r"send\s+(.+?)\s+to\s+(\w+)(?:\s+on\s+whatsapp)?$", text)
        
    whatsapp_robust = False
    contact = None
    message = None
    if whatsapp_match:
        whatsapp_robust = True
        if "and write" in text:
            contact = whatsapp_match.group(1).strip()
            message = whatsapp_match.group(2).strip()
        else:
            message = whatsapp_match.group(1).strip()
            contact = whatsapp_match.group(2).strip()
    elif "whatsapp" in text:
        if any(word in text for word in ("send", "write", "message", "msg", "text")):
            whatsapp_robust = True
            to_match = re.search(r"\bto\s+([a-zA-Z0-9_]+)\b", text, re.IGNORECASE)
            if to_match:
                contact = to_match.group(1).strip()
            
            quote_match = re.search(r"['\"](.+?)['\"]", text)
            if quote_match:
                message = quote_match.group(1).strip()
                
            if not message:
                m1 = re.search(r"\b(send|write|message|msg|text)\w*\s+(.+?)\s+to\s+", text, re.IGNORECASE)
                if m1:
                    message = m1.group(2).strip()
                    message = re.sub(r"\b(a|the|some|msg|message)\b", "", message, flags=re.IGNORECASE).strip()
                    
            if not contact:
                m2 = re.search(r"\b(send|write|message|msg|text)\w*\s+([a-zA-Z0-9_]+)\s+(.+)$", text, re.IGNORECASE)
                if m2:
                    contact = m2.group(2).strip()
                    message = m2.group(3).strip()

    if whatsapp_robust:
        contact = contact or "Harshita"
        message = message or "Hi!"
        contact = re.sub(r"[.!?]+$", "", contact).strip()
        message = re.sub(r"[.!?]+$", "", message).strip()
        contact = contact.capitalize()
        
        return PlannerOutput(
            intent="send_whatsapp",
            confidence=0.9,
            reasoning=f"Matched WhatsApp messaging flow for '{contact}'.",
            steps=[
                PlannerStep(tool="launch_application", args={"application": "WhatsApp"}, wait_for="ui_ready", timeout=60),
                PlannerStep(tool="search_inside_application", args={"query": contact}),
                PlannerStep(tool="press_key", args={"key": "enter"}),
                PlannerStep(tool="type_text", args={"text": message}),
                PlannerStep(tool="press_key", args={"key": "enter"})
            ]
        )

    # Rule 4b: Telegram Web browser messaging automation (decomposed sequence)
    if "telegram" in clean_text and any(w in clean_text for w in ("send", "message", "tell", "text", "bhejo", "saying")):
        if not re.match(r"^(open|launch|start|kholo|chalao)\s+telegram$", clean_text):
            from automation.telegram.nlu import parse_telegram_input
            res = parse_telegram_input("NEW_COMMAND", text)
            contact = (getattr(res, "recipient_query", "") or "").strip()
            msg = (getattr(res, "message_text", "") or "").strip()
            
            _PLACEHOLDERS = {"contact", "recipient", "{name}", "{contact}", "contact_name", "name", ""}
            if not contact or contact.lower() in _PLACEHOLDERS:
                return PlannerOutput(
                    intent="send_telegram_message",
                    confidence=0.0,
                    reasoning="Entity resolution failure: recipient contact missing or placeholder literal.",
                    steps=[]
                )

            if not msg or msg.lower() in {"message", "text", "{message}", ""}:
                msg = "hello"

            return PlannerOutput(
                intent="send_telegram_message",
                confidence=0.95,
                reasoning=f"Matched Telegram messaging flow for '{contact}'.",
                steps=[
                    PlannerStep(tool="open_telegram", args={}, description="Open Telegram Desktop or Web"),
                    PlannerStep(tool="search_telegram_contact", args={"contact": contact}, description=f"Search contact {contact}"),
                    PlannerStep(tool="verify_telegram_contact", args={"contact": contact}, description=f"Verify candidate {contact}"),
                    PlannerStep(tool="open_telegram_chat", args={"contact": contact}, description=f"Open chat with {contact}"),
                    PlannerStep(tool="verify_telegram_chat_header", args={"contact": contact}, description=f"Verify active chat header for {contact}"),
                    PlannerStep(tool="focus_telegram_composer", args={}, description="Focus Telegram message composer"),
                    PlannerStep(tool="type_telegram_message", args={"message": msg}, description=f"Type message '{msg}'"),
                    PlannerStep(tool="send_telegram_message", args={"contact": contact, "message": msg}, description="Dispatch send key on composer"),
                    PlannerStep(tool="verify_telegram_message_sent", args={"message": msg}, description="Verify outgoing message bubble"),
                    PlannerStep(tool="close_telegram_tab", args={}, description="Close Telegram session")
                ]
            )



    # Rule 5: Spotify automation (play/pause/resume)
    spotify_play_pattern = r"^(?:open\s+spotify\s+and\s+play|spotify\s+play|listen\s+to|play\s+song|play\s+music|play)\s+(.+)"
    spotify_play_match = re.match(spotify_play_pattern, text)
    if spotify_play_match:
        song = spotify_play_match.group(1).strip()
        song = re.sub(r"\b(on|in)\s+spotify$", "", song, flags=re.IGNORECASE).strip()
        song = re.sub(r"[.!?]+$", "", song).strip()
        
        return PlannerOutput(
            intent="play_music",
            confidence=0.9,
            reasoning=f"Matched Spotify play for song: '{song}'.",
            steps=[
                PlannerStep(tool="launch_application", args={"application": "Spotify"}, wait_for="ui_ready", timeout=60),
                PlannerStep(tool="search_inside_application", args={"query": song}),
                PlannerStep(tool="press_key", args={"key": "enter"}),
                PlannerStep(tool="press_key", args={"key": "enter"})
            ]
        )
            
    if text in ("pause", "pause it", "pause spotify", "pause music", "stop music", "pause song", "resume", "resume play", "play", "play music", "play song"):
        return PlannerOutput(
            intent="pause_music" if text in ("pause", "pause it", "pause spotify", "pause music", "stop music", "pause song") else "play_music",
            confidence=0.9,
            reasoning="Matched Spotify playback control.",
            steps=[
                PlannerStep(tool="launch_application", args={"application": "Spotify"}),
                PlannerStep(tool="press_key", args={"key": "playpause"})
            ]
        )

    # Intercept any other Spotify command before falling back to resolve_and_open
    if "spotify" in text:
        return PlannerOutput(
            intent="open_resource",
            confidence=0.9,
            reasoning="Matched Spotify application launch.",
            steps=[
                PlannerStep(tool="launch_application", args={"application": "Spotify"}, wait_for="ui_ready", timeout=60)
            ]
        )

    # Rule 6: Browser Web Search
    if re.search(r"\b(search|google|find\s+information|look\s+up)\b", text, re.IGNORECASE) and not re.search(r"\b(file|document|pdf|folder|directory|drive|local)\b", text, re.IGNORECASE):
        query_text = text
        query_text = re.sub(r"^(?:search\s+google\s+for|search\s+for|search\s+web\s+for|search|google|find\s+information\s+about|look\s+up)\s+", "", query_text, flags=re.IGNORECASE)
        query_text = re.sub(r"[.!?]+$", "", query_text).strip() or text
        return PlannerOutput(
            intent="search_web",
            confidence=0.9,
            reasoning=f"Matched browser search query: '{query_text}'",
            steps=[PlannerStep(tool="search_web", args={"query": query_text})]
        )

    # Rule 6.5: Open selected search result
    open_number_match = re.search(
        r"(?:open\s+)?(?:the\s+)?(?:number|result|doc|document)?\s*(#|\b)(one|two|three|four|five|first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|[1-5])\b(?:\s+(?:one|doc|document|file|result|item))?",
        text,
        re.IGNORECASE
    )
    if open_number_match and not any(kw in text.lower() for kw in ["healthsphere", "money", "mentor", "pdf", "docx", "pptx", "xlsx"]):
        num_str = open_number_match.group(2).strip()
        return PlannerOutput(
            intent="open_selected_document",
            confidence=0.95,
            reasoning=f"Matched open selected result: {num_str}",
            steps=[PlannerStep(tool="find_document_by_context", args={"result_number": num_str})]
        )

    # Rule 7: Open/launch resource dynamically (e.g. "open chatgpt", "launch vs code")
    match = re.match(r"(?:open|launch|run|start|go\s+to)\s+(.+)", text)
    if match:
        query = match.group(1).strip()
        query = re.sub(r"[.!?]+$", "", query).strip()
        
        from agentic.discovery.manager import find_best_resource
        res = find_best_resource(query)
        if res:
            if res.type == "website":
                return PlannerOutput(
                    intent="open_resource",
                    confidence=res.confidence,
                    reasoning=f"Fallback matched '{query}' to website: {res.name}",
                    steps=[PlannerStep(tool="open_browser", args={"url": res.url})]
                )
            elif res.type == "application":
                return PlannerOutput(
                    intent="open_resource",
                    confidence=res.confidence,
                    reasoning=f"Fallback matched '{query}' to application: {res.name}",
                    steps=[PlannerStep(tool="open_application", args={"application": res.name})]
                )
            elif res.type == "folder":
                return PlannerOutput(
                    intent="open_resource",
                    confidence=res.confidence,
                    reasoning=f"Fallback matched '{query}' to folder: {res.name}",
                    steps=[PlannerStep(tool="open_folder", args={"path": res.path})]
                )
            elif res.type == "file":
                return PlannerOutput(
                    intent="open_resource",
                    confidence=res.confidence,
                    reasoning=f"Fallback matched '{query}' to file: {res.name}",
                    steps=[PlannerStep(tool="open_file", args={"path": res.path})]
                )

    # Rule 8: Notepad Automation (supports single and compound commands)
    if "notepad" in text or any(word in text for word in ("write", "type", "append", "save file", "save notepad", "clear document", "clear notepad")):
        segments = []
        # Split by comma first
        for seg in text.split(","):
            # Further split by " and " / " then "
            sub_segs = re.split(r"\band\b|\bthen\b", seg)
            segments.extend(sub_segs)

        steps = []
        intent = "notepad_control"
        
        for s in segments:
            s_clean = s.strip().lower()
            if not s_clean:
                continue
                
            # Match actions:
            # 1. Open Notepad
            if any(p in s_clean for p in ("open notepad", "launch notepad", "start notepad", "notepad open")):
                steps.append(PlannerStep(tool="notepad_open", args={}))
                
            # 2. Save / Save As
            elif any(p in s_clean for p in ("save as", "save file as", "save notepad as", "save document as", "save file", "save notepad", "save the file", "save document", "save it")):
                fn_match = re.search(r"as\s+['\"]?([a-zA-Z0-9_\-\.]+)(?:\.txt)?['\"]?", s_clean)
                filename = fn_match.group(1) if fn_match else None
                if filename and not filename.endswith(".txt"):
                    filename += ".txt"
                
                # Check for optional target directory (e.g. "on desktop", "in documents", "to downloads")
                directory = None
                for dir_name in ("desktop", "documents", "downloads", "pictures"):
                    if dir_name in s_clean:
                        directory = dir_name.capitalize()
                        break
                
                # If directory not matched above, try regex match for general path strings
                if not directory:
                    dir_match = re.search(r"(?:in|into|on|to|onto)\s+['\"]?([a-zA-Z0-9_\-\.\:\\]+)['\"]?", s_clean)
                    if dir_match:
                        matched_dir = dir_match.group(1)
                        if matched_dir != filename:
                            directory = matched_dir
                
                # Check for overwrite flag
                overwrite = "overwrite" in s_clean or "replace" in s_clean or "force" in s_clean
                
                args = {}
                if filename:
                    args["filename"] = filename
                if directory:
                    args["directory"] = directory
                if overwrite:
                    args["overwrite"] = True
                    
                steps.append(PlannerStep(tool="notepad_save", args=args))
                
            # 4. Close Notepad
            elif any(p in s_clean for p in ("close notepad", "quit notepad", "exit notepad", "close it", "close the notepad", "close the file")) or s_clean == "close":
                # Check if we should save before close
                save_before = "save" in s_clean
                # Check if we discard changes (default to true, false if "don't discard" or similar)
                discard_changes = "discard" in s_clean or "dont save" in s_clean or "don't save" in s_clean or "discard changes" in s_clean
                if "save" in s_clean and "without saving" in s_clean:
                    discard_changes = True
                
                args = {}
                if save_before:
                    args["save_before_close"] = True
                if "don't discard" in s_clean or "do not discard" in s_clean:
                    args["discard_changes"] = False
                elif discard_changes:
                    args["discard_changes"] = True
                    
                steps.append(PlannerStep(tool="notepad_close", args=args))
                
            # 5. Type/Write/Append text
            elif s_clean.startswith("write ") or s_clean.startswith("type ") or s_clean.startswith("append ") or "write in notepad" in s_clean or "type in notepad" in s_clean:
                txt_match = re.search(r"(?:write|type|append)(?:\s+in\s+notepad)?\s+(?:text\s+)?['\"]?(.+?)['\"]?$", s_clean)
                txt = txt_match.group(1) if txt_match else ""
                if txt:
                    txt_clean = re.sub(r"^['\"]|['\"]$", "", txt)
                    # Strip trailing references to notepad from the typed text parameter itself
                    txt_clean = re.sub(r"\s+(?:in|into|to)\s+notepad$", "", txt_clean, flags=re.IGNORECASE).strip()
                    steps.append(PlannerStep(tool="notepad_type", args={"text": txt_clean}))
                    
            # 6. Press Enter / New Line
            elif any(p in s_clean for p in ("press enter", "new line", "next line", "press return")):
                steps.append(PlannerStep(tool="notepad_press_enter", args={}))
                
            # 7. Select All
            elif any(p in s_clean for p in ("select all", "select all text")):
                steps.append(PlannerStep(tool="notepad_select_all", args={}))
                
            # 8. Copy
            elif s_clean == "copy" or "copy text" in s_clean or "copy in notepad" in s_clean:
                steps.append(PlannerStep(tool="notepad_copy", args={}))
                
            # 9. Paste
            elif s_clean == "paste" or "paste text" in s_clean or "paste in notepad" in s_clean:
                steps.append(PlannerStep(tool="notepad_paste", args={}))
                
            # 10. Undo
            elif s_clean == "undo" or "undo last action" in s_clean or "undo in notepad" in s_clean:
                steps.append(PlannerStep(tool="notepad_undo", args={}))
                
            # 11. Redo
            elif s_clean == "redo" or "redo in notepad" in s_clean:
                steps.append(PlannerStep(tool="notepad_redo", args={}))
                
            # 12. Delete Text
            elif any(p in s_clean for p in ("delete text", "delete all text", "delete in notepad")):
                steps.append(PlannerStep(tool="notepad_delete", args={}))
                
            # 13. Clear Document
            elif any(p in s_clean for p in ("clear notepad", "clear document", "clear all", "empty notepad")):
                steps.append(PlannerStep(tool="notepad_clear", args={}))
                
            # 14. Open Existing File
            elif "open file" in s_clean or "open" in s_clean and "in notepad" in s_clean:
                path_match = re.search(r"(?:open file|open)\s+['\"]?([a-zA-Z0-9_\-\.\:\\]+)['\"]?", s_clean)
                path = path_match.group(1) if path_match else ""
                if path:
                    steps.append(PlannerStep(tool="notepad_open_file", args={"path": path}))
                    
            # 15. New File
            elif any(p in s_clean for p in ("new file", "new document", "create new file", "create a new file", "create a new text file", "new text file")):
                steps.append(PlannerStep(tool="notepad_new_file", args={}))

        if steps:
            return PlannerOutput(
                intent=intent,
                confidence=0.95,
                reasoning=f"Matched Notepad compound sequence flow for: '{text}'",
                steps=steps
            )

    # If no rules match, return standard safe fallback resolve_and_open
    return PlannerOutput.fallback("Could not parse offline plan.", query=transcription)
