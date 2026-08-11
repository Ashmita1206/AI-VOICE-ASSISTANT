"""
Filesystem Automation Tools
===========================

Provides tools for creating, deleting, listing, and opening files and folders safely.
"""

import os
import shutil
import sys
import subprocess
from pathlib import Path
from typing import Any

import config
from config import get_logger
from execution.registry import register_tool
from execution.schemas import ExecutionResult, ExecutionTimer

logger = get_logger(__name__)

def _resolve_safe_path(path_str: str) -> Path:
    """Resolve a path and ensure it's absolute."""
    path = Path(path_str).expanduser()
    if not path.is_absolute():
        path = Path.home() / path
    return path.resolve()

@register_tool("create_file")
def create_file(args: dict[str, Any]) -> ExecutionResult:
    """Create a file at the specified path."""
    path_str = args.get("path", "")
    if not path_str:
        return ExecutionResult(success=False, tool="create_file", message="No path provided.")
        
    with ExecutionTimer() as timer:
        try:
            path = _resolve_safe_path(path_str)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            return ExecutionResult(
                success=True,
                tool="create_file",
                message=f"Created file: {path.name}",
                execution_time_ms=timer.elapsed_ms
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                tool="create_file",
                message=f"Failed to create file: {e}",
                execution_time_ms=timer.elapsed_ms
            )

@register_tool("create_folder")
def create_folder(args: dict[str, Any]) -> ExecutionResult:
    """Create a folder/directory at the specified path."""
    path_str = args.get("path", "")
    if not path_str:
        return ExecutionResult(success=False, tool="create_folder", message="No path provided.")
        
    with ExecutionTimer() as timer:
        try:
            path = _resolve_safe_path(path_str)
            path.mkdir(parents=True, exist_ok=True)
            return ExecutionResult(
                success=True,
                tool="create_folder",
                message=f"Created folder: {path.name}",
                execution_time_ms=timer.elapsed_ms
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                tool="create_folder",
                message=f"Failed to create folder: {e}",
                execution_time_ms=timer.elapsed_ms
            )

@register_tool("delete_file")
def delete_file(args: dict[str, Any]) -> ExecutionResult:
    """Delete a file at the specified path."""
    path_str = args.get("path", "")
    if not path_str:
        return ExecutionResult(success=False, tool="delete_file", message="No path provided.")
        
    with ExecutionTimer() as timer:
        try:
            path = _resolve_safe_path(path_str)
            if not path.is_file():
                return ExecutionResult(
                    success=False,
                    tool="delete_file",
                    message="File not found.",
                    execution_time_ms=timer.elapsed_ms
                )
            path.unlink()
            return ExecutionResult(
                success=True,
                tool="delete_file",
                message=f"Deleted file: {path.name}",
                execution_time_ms=timer.elapsed_ms
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                tool="delete_file",
                message=f"Failed to delete file: {e}",
                execution_time_ms=timer.elapsed_ms
            )

@register_tool("delete_folder")
def delete_folder(args: dict[str, Any]) -> ExecutionResult:
    """Delete a folder and its contents recursively."""
    path_str = args.get("path", "")
    if not path_str:
        return ExecutionResult(success=False, tool="delete_folder", message="No path provided.")
        
    with ExecutionTimer() as timer:
        try:
            path = _resolve_safe_path(path_str)
            if not path.is_dir():
                return ExecutionResult(
                    success=False,
                    tool="delete_folder",
                    message="Folder not found.",
                    execution_time_ms=timer.elapsed_ms
                )
            shutil.rmtree(path)
            return ExecutionResult(
                success=True,
                tool="delete_folder",
                message=f"Deleted folder: {path.name}",
                execution_time_ms=timer.elapsed_ms
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                tool="delete_folder",
                message=f"Failed to delete folder: {e}",
                execution_time_ms=timer.elapsed_ms
            )

@register_tool("list_files")
def list_files(args: dict[str, Any]) -> ExecutionResult:
    """List files in the specified directory."""
    directory = args.get("directory", args.get("path", "."))
    if not directory:
        directory = "."
        
    with ExecutionTimer() as timer:
        try:
            path = _resolve_safe_path(directory)
            if not path.is_dir():
                return ExecutionResult(
                    success=False,
                    tool="list_files",
                    message=f"Directory '{directory}' not found.",
                    execution_time_ms=timer.elapsed_ms
                )
            files = os.listdir(path)
            files_str = "\n".join(files)
            return ExecutionResult(
                success=True,
                tool="list_files",
                message=f"Listed {len(files)} files in '{path.name}'.",
                output=files_str,
                execution_time_ms=timer.elapsed_ms
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                tool="list_files",
                message=f"Failed to list files in '{directory}': {e}",
                execution_time_ms=timer.elapsed_ms
            )

@register_tool("open_folder")
def open_folder(args: dict[str, Any]) -> ExecutionResult:
    """Open a folder in the OS file explorer."""
    path_str = args.get("path", "")
    if not path_str:
        return ExecutionResult(success=False, tool="open_folder", message="No path provided.")
        
    with ExecutionTimer() as timer:
        try:
            path = _resolve_safe_path(path_str)
            if not path.exists():
                from agentic.discovery.manager import find_best_resource
                res = find_best_resource(path_str, type_filter="folder")
                if res and res.path:
                    path = Path(res.path)
                else:
                    return ExecutionResult(
                        success=False,
                        tool="open_folder",
                        message=f"Folder '{path_str}' does not exist.",
                        execution_time_ms=timer.elapsed_ms
                    )
            
            spawned_proc = None
            if hasattr(os, "startfile"):
                os.startfile(path)
            else:
                if sys.platform.startswith("win"):
                    spawned_proc = subprocess.Popen(["explorer.exe", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                elif sys.platform == "darwin":
                    spawned_proc = subprocess.Popen(["open", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                else:
                    spawned_proc = subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    
            if spawned_proc is not None:
                import time
                time.sleep(0.2)
                retcode = spawned_proc.poll()
                if retcode is not None and retcode != 0:
                    stderr_msg = spawned_proc.stderr.read().decode('utf-8', errors='ignore').strip() if spawned_proc.stderr else ""
                    return ExecutionResult(
                        success=False,
                        tool="open_folder",
                        message=f"Failed to open folder: {stderr_msg or f'exit code {retcode}'}",
                        execution_time_ms=timer.elapsed_ms
                    )

            return ExecutionResult(
                success=True,
                tool="open_folder",
                message=f"Opened folder: {path}",
                execution_time_ms=timer.elapsed_ms
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                tool="open_folder",
                message=f"Failed to open folder: {e}",
                execution_time_ms=timer.elapsed_ms
            )

@register_tool("open_file")
def open_file(args: dict[str, Any]) -> ExecutionResult:
    """Open a file with the default associated application."""
    path_str = args.get("path", "")
    if not path_str:
        return ExecutionResult(success=False, tool="open_file", message="No path provided.")
        
    with ExecutionTimer() as timer:
        try:
            path = _resolve_safe_path(path_str)
            if not path.exists():
                from agentic.discovery.manager import find_best_resource
                res = find_best_resource(path_str, type_filter="file")
                if res and res.path:
                    path = Path(res.path)
                else:
                    return ExecutionResult(
                        success=False,
                        tool="open_file",
                        message=f"File '{path_str}' does not exist.",
                        execution_time_ms=timer.elapsed_ms
                    )
                    
            spawned_proc = None
            if hasattr(os, "startfile"):
                os.startfile(path)
            else:
                if sys.platform.startswith("win"):
                    spawned_proc = subprocess.Popen(["cmd.exe", "/c", "start", '""', str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                elif sys.platform == "darwin":
                    spawned_proc = subprocess.Popen(["open", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                else:
                    spawned_proc = subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    
            if spawned_proc is not None:
                import time
                time.sleep(0.2)
                retcode = spawned_proc.poll()
                if retcode is not None and retcode != 0:
                    stderr_msg = spawned_proc.stderr.read().decode('utf-8', errors='ignore').strip() if spawned_proc.stderr else ""
                    return ExecutionResult(
                        success=False,
                        tool="open_file",
                        message=f"Failed to open file: {stderr_msg or f'exit code {retcode}'}",
                        execution_time_ms=timer.elapsed_ms
                    )

            return ExecutionResult(
                success=True,
                tool="open_file",
                message=f"Opened file: {path}",
                execution_time_ms=timer.elapsed_ms
            )
        except Exception as e:
            return ExecutionResult(
                success=False,
                tool="open_file",
                message=f"Failed to open file: {e}",
                execution_time_ms=timer.elapsed_ms
            )
