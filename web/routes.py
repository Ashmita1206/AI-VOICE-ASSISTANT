"""
Flask API Routes
================

Defines all HTTP endpoints for the voice assistant web UI.
"""

import os
import tempfile
import logging

from flask import Blueprint, request, jsonify, Response, stream_with_context

from web.services import run_pipeline, get_health
from web.stream_service import run_pipeline_stream, run_confirmation_stream
from web.confirm_service import handle_confirm, get_pending_confirmation
from storage.history_manager import load_all, load_one, remove

logger = logging.getLogger(__name__)

api = Blueprint("api", __name__)


@api.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify(get_health())


@api.route("/transcribe", methods=["POST"])
def transcribe():
    """Receive audio and run the full pipeline."""
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided."}), 400

    audio_file = request.files["audio"]

    suffix = ".wav"
    if audio_file.filename and "." in audio_file.filename:
        suffix = "." + audio_file.filename.rsplit(".", 1)[1].lower()

    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)

    try:
        audio_file.save(temp_path)
        result = run_pipeline(temp_path)
        return jsonify(result)
    except Exception as e:
        logger.exception("Pipeline error")
        return jsonify({"error": str(e)}), 500
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@api.route("/transcribe_stream", methods=["POST"])
def transcribe_stream():
    """Receive audio or text and stream pipeline progress as Server-Sent Events."""
    json_data = request.get_json(silent=True) or {}
    text_input = request.form.get("text") or json_data.get("text")
    if text_input:
        def generate_text_stream():
            try:
                yield from run_pipeline_stream(text=text_input)
            except Exception as exc:
                logger.exception("Streaming pipeline error (text)")
                import json
                yield f'data: {{"stage":"done","status":"error","message":{json.dumps(str(exc))}}}\n\n'
                
        return Response(
            stream_with_context(generate_text_stream()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream; charset=utf-8",
            },
        )

    if "audio" not in request.files:
        return jsonify({"error": "No audio or text provided."}), 400

    audio_file = request.files["audio"]

    suffix = ".wav"
    if audio_file.filename and "." in audio_file.filename:
        suffix = "." + audio_file.filename.rsplit(".", 1)[1].lower()

    fd, temp_path = tempfile.mkstemp(suffix=suffix)
    os.close(fd)

    try:
        audio_file.save(temp_path)
    except Exception as e:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return jsonify({"error": str(e)}), 500

    def generate_and_cleanup():
        try:
            yield from run_pipeline_stream(audio_path=temp_path)
        except Exception as exc:
            logger.exception("Streaming pipeline error")
            import json
            yield f'data: {{"stage":"done","status":"error","message":{json.dumps(str(exc))}}}\n\n'
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    return Response(
        stream_with_context(generate_and_cleanup()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream; charset=utf-8",
        },
    )


@api.route("/history", methods=["GET"])
def history():
    """Return all sessions from persistent storage."""
    return jsonify(load_all())


@api.route("/session/<session_id>", methods=["GET"])
def session_detail(session_id):
    """Return a single session by ID."""
    session = load_one(session_id)
    if session is None:
        return jsonify({"error": "Session not found."}), 404
    return jsonify(session)


@api.route("/session/<session_id>", methods=["DELETE"])
def session_delete(session_id):
    """Delete a session by ID."""
    deleted = remove(session_id)
    if deleted:
        return jsonify({"status": "deleted"})
    return jsonify({"error": "Session not found."}), 404


@api.route("/speak", methods=["POST"])
def speak():
    """Text-to-speech only endpoint."""
    data = request.get_json(silent=True) or {}
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "No text provided."}), 400

    from web.services import _generate_tts_file
    path = _generate_tts_file(text)
    if path:
        filename = os.path.basename(path)
        return jsonify({"audio_url": f"/static/audio/{filename}"})
    return jsonify({"error": "TTS generation failed."}), 500


# ══════════════════════════════════════════════════════════════════════
# Confirmation Endpoints
# ══════════════════════════════════════════════════════════════════════

@api.route("/confirm", methods=["POST"])
def confirm():
    """Handle a user's confirmation decision (proceed or cancel).

    Request body:
        {
            "confirmation_id": "<uuid>",
            "decision": "proceed" | "cancel",
            "edited_steps": [...]
        }
    """
    data = request.get_json(silent=True) or {}

    confirmation_id = data.get("confirmation_id")
    decision = data.get("decision")
    edited_steps = data.get("edited_steps")

    if not confirmation_id:
        return jsonify({"success": False, "message": "Missing confirmation_id."}), 400
    if decision not in ("proceed", "cancel"):
        return jsonify({"success": False, "message": "Decision must be 'proceed' or 'cancel'."}), 400

    try:
        # Check if client accepts text/event-stream or has explicitly requested streaming
        wants_stream = (
            request.args.get("stream") == "true" or
            "text/event-stream" in request.headers.get("Accept", "")
        )

        if decision == "cancel" or not wants_stream:
            result = handle_confirm(confirmation_id, decision, edited_steps)
            return jsonify(result), 200

        # Stream execution progress for proceed decision when streaming is desired
        def generate():
            try:
                yield from run_confirmation_stream(confirmation_id, edited_steps)
            except Exception as exc:
                logger.exception("Streaming execution error")
                import json
                yield f'data: {{"stage":"done","status":"error","message":{json.dumps(str(exc))}}}\n\n'

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
                "Content-Type": "text/event-stream; charset=utf-8",
            },
        )
    except Exception as e:
        logger.exception("Confirmation error")
        return jsonify({"success": False, "message": str(e)}), 500


@api.route("/pending", methods=["GET"])
def pending():
    """Return any currently pending confirmation for the frontend.

    This lets the UI restore the confirmation card after a page refresh.
    Returns null/empty if no pending action exists.
    """
    confirmation = get_pending_confirmation()
    return jsonify({"confirmation": confirmation})


@api.route("/permissions/check", methods=["POST"])
def permissions_check():
    """Verify check status of specified permissions."""
    data = request.get_json(silent=True) or {}
    permissions = data.get("permissions", [])
    from agentic.permissions_check import check_all_required_permissions
    results = check_all_required_permissions(permissions)
    return jsonify({"success": True, "granted": results})


@api.route("/permissions/grant", methods=["POST"])
def permissions_grant():
    """Trigger OS-level grant dialog or settings page for a permission."""
    data = request.get_json(silent=True) or {}
    permission = data.get("permission")
    if not permission:
        return jsonify({"success": False, "error": "Missing permission name"}), 400
    from agentic.permissions_check import grant_os_permission
    success = grant_os_permission(permission)
    return jsonify({"success": success, "permission": permission})


@api.route("/permissions/mock", methods=["POST"])
def permissions_mock():
    """Allow mock setting of system permissions for validation/testing flows."""
    data = request.get_json(silent=True) or {}
    permission = data.get("permission")
    granted = data.get("granted", True)
    if not permission:
        return jsonify({"success": False, "error": "Missing permission name"}), 400
    from agentic.permissions_check import set_mock_permission
    set_mock_permission(permission, granted)
    return jsonify({"success": True, "permission": permission, "granted": granted})


@api.route("/view_document", methods=["GET"])
def view_document():
    """Serve a local document for viewing directly inside the web browser tab."""
    raw_path = request.args.get("path", "")
    if not raw_path:
        return jsonify({"error": "Missing path parameter"}), 400

    import urllib.parse
    file_path = urllib.parse.unquote_plus(raw_path)
    abs_path = os.path.abspath(file_path)

    if not os.path.exists(abs_path):
        logger.error("[VIEW DOC] File not found: %s (raw path: %s)", abs_path, raw_path)
        return jsonify({"error": "File not found", "path": abs_path}), 404

    from flask import send_file
    import mimetypes
    mime_type, _ = mimetypes.guess_type(abs_path)
    return send_file(abs_path, mimetype=mime_type or "application/octet-stream", as_attachment=False)


