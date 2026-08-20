"""
Permission Engine
=================

Governs which tools are safe to execute immediately and which require explicit
user confirmation before proceeding.
"""

class PermissionManager:
    """Manages permissions and confirmation prompts for tools."""
    
    # Tools that execute immediately without user confirmation
    SAFE_TOOLS = {
        "search_web",
        "create_file",
        "create_folder",
        "read_directory",
        "list_files",
        "open_terminal",
        "open_file_manager",
        "check_time",
        "check_memory",
        "system_info",
        "type_text",
        "press_key",
        "hotkey",
        "open_application",
        "open_browser",
        "open_folder",
        "open_file",
        "open_website",
        "open_whatsapp",
        "resolve_and_open",
        "is_app_running",
        "activate_window",
        "get_active_window",
        "perform_app_action",
        # Fine-grained automation tasks
        "focus_window",
        "launch_application",
        "wait_for_window",
        "click",
        "double_click",
        "right_click",
        "scroll",
        "copy",
        "paste",
        "drag",
        "find_text",
        "ocr",
        "locate_ui_element",
        "wait_until",
        "search_inside_application",
        "close_window",
        "switch_tab",
        "select_dropdown",
        # Stateful execution engine wait primitives
        "wait_until_process_running",
        "wait_until_window_exists",
        "wait_until_window_active",
        "wait_until_application_ready",
        "wait_until_element_ready",
        "wait_until_browser_loaded",
        # Telegram fine-grained automation tools (self-governing confirmations)
        "open_telegram",
        "open_telegram_web",
        "open_telegram_web_only",
        "search_telegram_contact",
        "verify_telegram_contact",
        "open_telegram_chat",
        "verify_telegram_chat_header",
        "focus_telegram_composer",
        "type_telegram_message",
        "send_telegram_message",
        "verify_telegram_message_sent",
        "verify_telegram_message_bubble",
        "close_telegram_tab",
        "close_telegram",
    }
    
    # Tools that always require explicit button confirmation
    DANGEROUS_TOOLS = {
        "delete_file",
        "delete_folder",
        "shutdown_system",
        "reboot_system",
        "execute_shell",
        "send_whatsapp_message",
        "take_screenshot",
        "open_gmail",
        "open_spotify",
    }

    @classmethod
    def is_safe(cls, tool_name: str) -> bool:
        """Return True if the tool can execute without asking."""
        return tool_name in cls.SAFE_TOOLS

    @classmethod
    def requires_confirmation(cls, tool_name: str, args: dict = None) -> bool:
        """Return True if the tool requires explicit confirmation."""
        if tool_name in ("open_gmail", "open_spotify"):
            return True
        if tool_name == "perform_app_action" and args:
            app = args.get("app", "").lower()
            action = args.get("action", "").lower()
            if app == "whatsapp" and action == "send_message":
                return True
        return tool_name not in cls.SAFE_TOOLS

    @classmethod
    def build_confirmation_message(cls, tool_name: str, args: dict) -> str:
        """Generate a natural language confirmation prompt for dangerous tools."""
        if tool_name == "open_gmail":
            return "Open Gmail? (Requires Network Access permission)"

        if tool_name == "open_spotify":
            return "Open Spotify? (Requires System & Network Access permission)"

        if tool_name == "open_website":
            url = args.get("url", "the website")
            return f"Open {url}?"

        if tool_name == "open_application":
            app = args.get("application", args.get("name", "the application"))
            return f"Open {app}?"
        
        if tool_name == "open_browser":
            return "Open the browser?"

        if tool_name == "open_whatsapp":
            return "Open WhatsApp?"
            
        if tool_name == "delete_file":
            filename = args.get("path", "the file")
            return f"Delete {filename}?"
            
        if tool_name == "delete_folder":
            foldername = args.get("path", "the folder")
            return f"Delete the folder {foldername}?"
            
        if tool_name == "shutdown_system":
            return "Shutdown the system?"
            
        if tool_name == "reboot_system":
            return "Reboot the system?"
            
        if tool_name == "type_message" or tool_name == "send_whatsapp_message":
            contact = args.get("contact", "the contact")
            message = args.get("message", "")
            if message:
                return f"Should I send this message to {contact}?\n\n{message}"
            return f"Should I send a message to {contact}?"

        if tool_name == "perform_app_action" and args:
            app = args.get("app", "").lower()
            action = args.get("action", "").lower()
            if app == "whatsapp" and action == "send_message":
                payload = args.get("payload", {})
                contact = payload.get("contact", "the contact")
                message = payload.get("message", "")
                if message:
                    return f"Should I send this message to {contact}?\n\n{message}"
                return f"Should I send a message to {contact}?"
            
        if tool_name == "execute_shell":
            cmd = args.get("command", args.get("cmd", ""))
            return f"Execute shell command?\n\n{cmd}" if cmd else "Execute shell command?"

        if tool_name == "take_screenshot":
            return "Take a screenshot?"

        return f"Execute {tool_name}?"

