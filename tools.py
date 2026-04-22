"""File system and command execution tools for the AI assistant."""
import os
import re
import subprocess
import json
from pathlib import Path
from typing import Any

import config

# Track active subprocesses so they can be killed on app exit
_active_processes: set[subprocess.Popen] = set()


def cleanup_processes():
    """Kill all tracked subprocesses. Called on application shutdown."""
    for proc in list(_active_processes):
        try:
            proc.kill()
        except Exception:
            pass
    _active_processes.clear()


def _resolve_path(relative_path: str) -> Path:
    """Resolve and validate path stays within workspace."""
    workspace_path = config.WORKSPACE_PATH
    path = (workspace_path / relative_path).resolve()
    workspace = workspace_path.resolve()
    if not str(path).startswith(str(workspace)):
        raise PermissionError(f"Path {relative_path} is outside workspace")
    for part in path.parts:
        if part in config.BLOCKED_PATHS:
            raise PermissionError(f"Access to {part} is not allowed")
    return path


def list_files(directory: str = ".", recursive: bool = False, pattern: str | None = None) -> str:
    """List files and subdirectories in a directory.
    
    Args:
        directory: Path relative to workspace (default: current)
        recursive: If True, list recursively
        pattern: Optional glob pattern to filter (e.g. "*.py")
    """
    try:
        path = _resolve_path(directory)
        if not path.exists():
            return f"Error: Directory '{directory}' does not exist."
        if not path.is_dir():
            return f"Error: '{directory}' is not a directory."
        
        items = []
        if recursive:
            for p in path.rglob("*"):
                rel = p.relative_to(path)
                if any(part in config.BLOCKED_PATHS for part in rel.parts):
                    continue
                items.append(str(rel))
        else:
            for p in sorted(path.iterdir()):
                if p.name in config.BLOCKED_PATHS or p.name.startswith("."):
                    continue
                items.append(p.name + ("/" if p.is_dir() else ""))
        
        if pattern:
            import fnmatch
            items = [i for i in items if fnmatch.fnmatch(i, pattern)]
        
        return json.dumps({"path": str(directory), "items": items[:100]})
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {str(e)}"


def read_file(file_path: str) -> str:
    """Read the contents of a file.
    
    Args:
        file_path: Path relative to workspace
    """
    try:
        path = _resolve_path(file_path)
        if not path.exists():
            return f"Error: File '{file_path}' does not exist."
        if not path.is_file():
            return f"Error: '{file_path}' is not a file."
        
        content = path.read_text(encoding="utf-8", errors="replace")
        return json.dumps({
            "path": file_path,
            "content": content,
            "lines": len(content.splitlines()),
        })
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {str(e)}"


def search_code(query: str, path: str = ".", file_pattern: str | None = None) -> str:
    """Search for text/code in files. Uses simple line-by-line search.
    
    Args:
        query: Text or regex pattern to search for
        path: Directory to search in (default: workspace root)
        file_pattern: Optional glob to filter files (e.g. "*.py")
    """
    try:
        base = _resolve_path(path)
        if not base.exists() or not base.is_dir():
            return f"Error: Path '{path}' is not a valid directory."
        
        import fnmatch
        try:
            regex = re.compile(query)
        except re.error:
            regex = re.compile(re.escape(query), re.IGNORECASE)
        
        results = []
        for file_path in base.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in config.BLOCKED_PATHS for part in file_path.relative_to(base).parts):
                continue
            if file_pattern and not fnmatch.fnmatch(file_path.name, file_pattern):
                continue
            
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                rel_path = str(file_path.relative_to(config.WORKSPACE_PATH))
                for i, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        results.append({"file": rel_path, "line": i, "content": line.strip()})
                        if len(results) >= 50:
                            break
            except (OSError, UnicodeDecodeError):
                pass
            if len(results) >= 50:
                break
        
        return json.dumps({"query": query, "results": results})
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {str(e)}"


def write_file(file_path: str, content: str) -> str:
    """Write content to a file. Creates parent directories if needed.
    
    Args:
        file_path: Path relative to workspace
        content: Full file content to write
    """
    try:
        path = _resolve_path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return json.dumps({"success": True, "path": file_path})
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {str(e)}"


def search_replace(file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    """Replace text in a file.
    
    Args:
        file_path: Path relative to workspace
        old_string: Exact text to find (or regex if replace_all)
        new_string: Replacement text
        replace_all: If True, replace all occurrences
    """
    try:
        path = _resolve_path(file_path)
        if not path.exists():
            return f"Error: File '{file_path}' does not exist."
        
        content = path.read_text(encoding="utf-8")
        if replace_all:
            new_content = content.replace(old_string, new_string)
        else:
            if old_string not in content:
                return f"Error: Could not find '{old_string[:80]}...' in file."
            new_content = content.replace(old_string, new_string, 1)
        
        path.write_text(new_content, encoding="utf-8")
        return json.dumps({"success": True, "path": file_path, "replacements": content.count(old_string) if replace_all else 1})
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {str(e)}"


def find_definition(symbol: str, file_pattern: str | None = None) -> str:
    """Find where a function, class, or variable is defined.
    
    Args:
        symbol: Name of the symbol to find (function, class, variable)
        file_pattern: Optional glob to filter files (e.g. "*.py")
    """
    try:
        import fnmatch
        results = []
        for file_path in config.WORKSPACE_PATH.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in config.BLOCKED_PATHS for part in file_path.relative_to(config.WORKSPACE_PATH).parts):
                continue
            if file_pattern and not fnmatch.fnmatch(file_path.name, file_pattern):
                continue
            
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                rel_path = str(file_path.relative_to(config.WORKSPACE_PATH))
                lines = content.splitlines()
                
                # Common patterns for definitions
                patterns = [
                    rf"^\s*(def|class|async def)\s+{re.escape(symbol)}\s*[\(:]",  # def/class
                    rf"^\s*{re.escape(symbol)}\s*=",  # variable assignment
                    rf"^\s*{re.escape(symbol)}\s*:",  # type annotation
                ]
                
                for i, line in enumerate(lines, 1):
                    for pattern in patterns:
                        if re.search(pattern, line):
                            # Get context (3 lines before and after)
                            start = max(0, i - 4)
                            end = min(len(lines), i + 3)
                            context = "\n".join(lines[start:end])
                            results.append({
                                "file": rel_path,
                                "line": i,
                                "content": line.strip(),
                                "context": context,
                            })
                            break
                    if len(results) >= 20:
                        break
            except (OSError, UnicodeDecodeError):
                pass
            if len(results) >= 20:
                break
        
        return json.dumps({"symbol": symbol, "results": results})
    except Exception as e:
        return f"Error: {str(e)}"


def find_usages(symbol: str, file_pattern: str | None = None) -> str:
    """Find all usages of a function, class, or variable.
    
    Args:
        symbol: Name of the symbol to find usages for
        file_pattern: Optional glob to filter files (e.g. "*.py")
    """
    try:
        import fnmatch
        results = []
        for file_path in config.WORKSPACE_PATH.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in config.BLOCKED_PATHS for part in file_path.relative_to(config.WORKSPACE_PATH).parts):
                continue
            if file_pattern and not fnmatch.fnmatch(file_path.name, file_pattern):
                continue
            
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                rel_path = str(file_path.relative_to(config.WORKSPACE_PATH))
                lines = content.splitlines()
                
                # Pattern to find usages (not definitions)
                usage_pattern = rf"\b{re.escape(symbol)}\b"
                
                for i, line in enumerate(lines, 1):
                    if re.search(usage_pattern, line):
                        # Skip if it's a definition
                        if re.search(rf"^\s*(def|class|async def)\s+{re.escape(symbol)}\s*[\(:]", line):
                            continue
                        if re.search(rf"^\s*{re.escape(symbol)}\s*=", line):
                            continue
                        
                        results.append({
                            "file": rel_path,
                            "line": i,
                            "content": line.strip(),
                        })
                        if len(results) >= 50:
                            break
            except (OSError, UnicodeDecodeError):
                pass
            if len(results) >= 50:
                break
        
        return json.dumps({"symbol": symbol, "results": results})
    except Exception as e:
        return f"Error: {str(e)}"


def search_code_with_context(query: str, path: str = ".", file_pattern: str | None = None, context_lines: int = 3) -> str:
    """Search for code with surrounding context lines for better understanding.
    
    Args:
        query: Text or regex pattern to search for
        path: Directory to search in
        file_pattern: Optional glob to filter files
        context_lines: Number of lines before/after to include (default: 3)
    """
    try:
        base = _resolve_path(path)
        if not base.exists() or not base.is_dir():
            return f"Error: Path '{path}' is not a valid directory."
        
        import fnmatch
        try:
            regex = re.compile(query)
        except re.error:
            regex = re.compile(re.escape(query), re.IGNORECASE)
        
        results = []
        for file_path in base.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in config.BLOCKED_PATHS for part in file_path.relative_to(base).parts):
                continue
            if file_pattern and not fnmatch.fnmatch(file_path.name, file_pattern):
                continue
            
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                rel_path = str(file_path.relative_to(config.WORKSPACE_PATH))
                lines = content.splitlines()
                
                for i, line in enumerate(lines, 1):
                    if regex.search(line):
                        start = max(0, i - context_lines - 1)
                        end = min(len(lines), i + context_lines)
                        context = "\n".join(lines[start:end])
                        results.append({
                            "file": rel_path,
                            "line": i,
                            "content": line.strip(),
                            "context": context,
                        })
                        if len(results) >= 30:
                            break
            except (OSError, UnicodeDecodeError):
                pass
            if len(results) >= 30:
                break
        
        return json.dumps({"query": query, "results": results})
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {str(e)}"


def get_file_info(file_path: str) -> str:
    """Get metadata about a file (size, lines, language, etc.).
    
    Args:
        file_path: Path to file
    """
    try:
        path = _resolve_path(file_path)
        if not path.exists():
            return f"Error: File '{file_path}' does not exist."
        if not path.is_file():
            return f"Error: '{file_path}' is not a file."
        
        content = path.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        
        # Detect language from extension
        ext = path.suffix.lower()
        lang_map = {
            ".py": "python", ".js": "javascript", ".ts": "typescript",
            ".jsx": "javascript", ".tsx": "typescript", ".java": "java",
            ".cpp": "cpp", ".c": "c", ".rs": "rust", ".go": "go",
            ".rb": "ruby", ".php": "php", ".swift": "swift",
            ".kt": "kotlin", ".scala": "scala", ".html": "html",
            ".css": "css", ".json": "json", ".xml": "xml",
            ".md": "markdown", ".sh": "bash", ".bat": "batch",
        }
        
        return json.dumps({
            "path": file_path,
            "size_bytes": path.stat().st_size,
            "lines": len(lines),
            "language": lang_map.get(ext, "unknown"),
            "extension": ext,
        })
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {str(e)}"


def run_command(command: str, cwd: str | None = None, timeout: int = 60) -> str:
    """Execute a shell command. Use for debugging, tests, builds.
    
    Args:
        command: Shell command to run (e.g. "npm run build", "python test.py")
        cwd: Working directory (default: workspace root)
        timeout: Timeout in seconds (default: 60)
    """
    try:
        work_dir = _resolve_path(cwd or ".") if cwd else config.WORKSPACE_PATH
        if not work_dir.exists() or not work_dir.is_dir():
            return f"Error: Working directory '{cwd}' does not exist."
        
        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=work_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ},
        )
        _active_processes.add(proc)
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            _active_processes.discard(proc)
            return json.dumps({"command": command, "error": "Command timed out"})
        finally:
            _active_processes.discard(proc)
        
        output = stdout + ("\n" + stderr if stderr else "")
        return json.dumps({
            "command": command,
            "exit_code": proc.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "output": output.strip() or "(no output)",
        })
    except PermissionError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: {str(e)}"


def _tool(name: str, desc: str, props: dict, required: list | None = None) -> dict:
    """Helper to build a compact tool definition."""
    schema: dict = {"type": "object", "properties": props}
    if required:
        schema["required"] = required
    return {"type": "function", "function": {"name": name, "description": desc, "parameters": schema}}


# Compact path/glob reusable fragments
_PATH = {"type": "string"}
_GLOB = {"type": "string"}

TOOL_DEFINITIONS = [
    _tool("list_files", "List directory contents",
          {"directory": _PATH, "recursive": {"type": "boolean"}, "pattern": _GLOB}),
    _tool("read_file", "Read file contents",
          {"file_path": _PATH}, ["file_path"]),
    _tool("search_code", "Regex/text search across files",
          {"query": {"type": "string"}, "path": _PATH, "file_pattern": _GLOB}, ["query"]),
    _tool("search_code_with_context", "Search with surrounding context lines",
          {"query": {"type": "string"}, "path": _PATH, "file_pattern": _GLOB,
           "context_lines": {"type": "integer"}}, ["query"]),
    _tool("write_file", "Create or overwrite a file",
          {"file_path": _PATH, "content": {"type": "string"}}, ["file_path", "content"]),
    _tool("search_replace", "Replace text in a file (prefer for small edits)",
          {"file_path": _PATH, "old_string": {"type": "string"},
           "new_string": {"type": "string"}, "replace_all": {"type": "boolean"}},
          ["file_path", "old_string", "new_string"]),
    _tool("run_command", "Execute a shell command",
          {"command": {"type": "string"}, "cwd": _PATH, "timeout": {"type": "integer"}},
          ["command"]),
    _tool("find_definition", "Find symbol definition",
          {"symbol": {"type": "string"}, "file_pattern": _GLOB}, ["symbol"]),
    _tool("find_usages", "Find all usages of a symbol",
          {"symbol": {"type": "string"}, "file_pattern": _GLOB}, ["symbol"]),
    _tool("get_file_info", "Get file metadata (size, lines, language)",
          {"file_path": _PATH}, ["file_path"]),
]


def execute_tool(name: str, arguments: dict[str, Any]) -> str:
    """Execute a tool by name with given arguments."""
    tools_map = {
        "list_files": list_files,
        "read_file": read_file,
        "search_code": search_code,
        "write_file": write_file,
        "search_replace": search_replace,
        "run_command": run_command,
        "find_definition": find_definition,
        "find_usages": find_usages,
        "search_code_with_context": search_code_with_context,
        "get_file_info": get_file_info,
    }
    fn = tools_map.get(name)
    if not fn:
        return f"Error: Unknown tool '{name}'"
    try:
        # Filter out None values and apply defaults
        filtered_args = {k: v for k, v in arguments.items() if v is not None}
        return fn(**filtered_args)
    except TypeError as e:
        return f"Error: Invalid arguments: {e}"
