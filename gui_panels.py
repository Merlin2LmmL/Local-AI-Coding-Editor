"""Panel components for the AI Code Assistant GUI."""
import json, os, re
from pathlib import Path
from dataclasses import dataclass, field
from tkinter import (Frame, Label, Button, Text, Scrollbar, BooleanVar,
                     Checkbutton, Entry, StringVar, messagebox, ttk, Listbox)
from tkinter.scrolledtext import ScrolledText
from tkinter import filedialog
import config


@dataclass
class AgentExecution:
    step_index: int
    step_total: int
    step_description: str
    tool_calls: list = field(default_factory=list)
    raw_output: str = ""
    status: str = "pending"  # pending | running | done | error


# ── File Browser Panel ──────────────────────────────────────────────
class FileBrowserPanel(Frame):
    def __init__(self, parent, on_file_open=None, **kw):
        super().__init__(parent, bg="#1e1e1e", **kw)
        self.on_file_open = on_file_open
        self._build()
        self.refresh()

    def _build(self):
        hdr = Frame(self, bg="#252526")
        hdr.pack(fill="x")
        Label(hdr, text="  EXPLORER", font=("Segoe UI", 9, "bold"),
              bg="#252526", fg="#bbbbbb").pack(side="left", pady=6)
        Button(hdr, text="⟳", font=("Segoe UI", 9), bg="#252526", fg="#cccccc",
               relief="flat", command=self.refresh, cursor="hand2",
               bd=0).pack(side="right", padx=6)

        tree_frame = Frame(self, bg="#1e1e1e")
        tree_frame.pack(fill="both", expand=True)

        self.tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse")
        sb = Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background="#1e1e1e", foreground="#e0e0e0",
                        fieldbackground="#1e1e1e", font=("Segoe UI", 10),
                        rowheight=24, borderwidth=0)
        style.configure("Treeview.Heading", background="#252526",
                        foreground="#bbbbbb")
        style.map("Treeview", background=[("selected", "#37373d")],
                  foreground=[("selected", "#ffffff")])

        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", self._on_double_click)
        self.tree.bind("<<TreeviewOpen>>", self._on_expand)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        root_path = config.WORKSPACE_PATH.resolve()
        root_id = self.tree.insert("", "end", text=root_path.name,
                                   values=[str(root_path)], open=True)
        self._populate(root_id, root_path)

    def _populate(self, parent_id, path, depth=0):
        if depth > 1:
            return
        try:
            items = sorted(path.iterdir(),
                          key=lambda p: (not p.is_dir(), p.name.lower()))
            for item in items:
                if item.name.startswith(".") or item.name in config.BLOCKED_PATHS:
                    continue
                if item.is_dir():
                    nid = self.tree.insert(parent_id, "end",
                                          text="📁 " + item.name,
                                          values=[str(item)])
                    # placeholder for lazy loading
                    self.tree.insert(nid, "end", text="")
                else:
                    icon = self._file_icon(item.suffix)
                    self.tree.insert(parent_id, "end",
                                    text=f"{icon} {item.name}",
                                    values=[str(item)])
        except PermissionError:
            pass

    def _on_expand(self, event):
        item = self.tree.focus()
        children = self.tree.get_children(item)
        if len(children) == 1 and self.tree.item(children[0], "text") == "":
            self.tree.delete(children[0])
            path = Path(self.tree.item(item, "values")[0])
            self._populate(item, path, depth=0)

    def _on_double_click(self, event):
        item = self.tree.focus()
        if not item:
            return
        path = Path(self.tree.item(item, "values")[0])
        if path.is_file() and self.on_file_open:
            self.on_file_open(path)

    @staticmethod
    def _file_icon(ext):
        icons = {".py": "🐍", ".js": "📜", ".ts": "📘", ".html": "🌐",
                 ".css": "🎨", ".json": "📋", ".md": "📝", ".txt": "📄",
                 ".bat": "⚙️", ".sh": "⚙️", ".yml": "⚙️", ".yaml": "⚙️"}
        return icons.get(ext.lower(), "📄")


# ── Tabbed Viewer Panel ─────────────────────────────────────────────
class TabbedViewerPanel(Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, bg="#1e1e1e", **kw)
        self._tabs = {}  # key -> tab_id
        self._build()

    def _build(self):
        style = ttk.Style()
        style.configure("Viewer.TNotebook", background="#1e1e1e",
                        borderwidth=0)
        style.configure("Viewer.TNotebook.Tab", background="#2d2d2d",
                        foreground="#bbbbbb", padding=[12, 6],
                        font=("Segoe UI", 9))
        style.map("Viewer.TNotebook.Tab",
                  background=[("selected", "#1e1e1e")],
                  foreground=[("selected", "#ffffff")])

        self.notebook = ttk.Notebook(self, style="Viewer.TNotebook")
        self.notebook.pack(fill="both", expand=True)
        self.notebook.bind("<Button-3>", self._on_right_click)
        self.notebook.bind("<Button-2>", self._on_right_click)
        self._show_welcome()

    def _show_welcome(self):
        f = Frame(self.notebook, bg="#1e1e1e")
        Label(f, text="Welcome", font=("Segoe UI", 22, "bold"),
              bg="#1e1e1e", fg="#555555").pack(expand=True)
        Label(f, text="Double-click a file to open it\nClick an agent step to inspect it\nRight-click or Middle-click a tab to close it",
              font=("Segoe UI", 11), bg="#1e1e1e", fg="#444444").pack()
        self.notebook.add(f, text=" Welcome ")
        self._tabs["__welcome__"] = f

    def open_file(self, filepath: Path):
        key = str(filepath)
        if key in self._tabs:
            self.notebook.select(self._tabs[key])
            return
        f = Frame(self.notebook, bg="#1e1e1e")
        txt = ScrolledText(f, wrap="none", font=("Consolas", 11),
                           bg="#1e1e1e", fg="#d4d4d4", insertbackground="#fff",
                           selectbackground="#264f78", relief="flat",
                           padx=10, pady=10)
        txt.pack(fill="both", expand=True)
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
            txt.insert("1.0", content)
            self._apply_syntax(txt, filepath.suffix)
        except Exception as e:
            txt.insert("1.0", f"Error reading file: {e}")
        txt.config(state="disabled")
        name = filepath.name
        if len(name) > 20:
            name = name[:17] + "..."
        self.notebook.add(f, text=f" {name} ✕ ")
        self.notebook.select(f)
        self._tabs[key] = f

    def open_agent_view(self, agent: AgentExecution):
        key = f"__agent_{agent.step_index}__"
        if key in self._tabs:
            # Update existing
            self.notebook.select(self._tabs[key])
            self._update_agent_tab(self._tabs[key], agent)
            return
        f = Frame(self.notebook, bg="#1e1e1e")
        self._build_agent_content(f, agent)
        title = f" Step {agent.step_index}/{agent.step_total} "
        self.notebook.add(f, text=title)
        self.notebook.select(f)
        self._tabs[key] = f

    def _build_agent_content(self, parent, agent: AgentExecution):
        for w in parent.winfo_children():
            w.destroy()
        txt = ScrolledText(parent, wrap="word", font=("Consolas", 11),
                           bg="#1e1e1e", fg="#d4d4d4", relief="flat",
                           padx=15, pady=15)
        txt.pack(fill="both", expand=True)
        txt.tag_config("heading", foreground="#c084fc",
                       font=("Consolas", 13, "bold"))
        txt.tag_config("tool_name", foreground="#fbbf24",
                       font=("Consolas", 11, "bold"))
        txt.tag_config("success", foreground="#34d399")
        txt.tag_config("error", foreground="#f87171")
        txt.tag_config("dim", foreground="#888888",
                       font=("Consolas", 10))
        txt.tag_config("raw", foreground="#999999",
                       font=("Consolas", 10))

        status_icon = {"pending": "⬜", "running": "🔄",
                       "done": "✅", "error": "❌"}.get(agent.status, "?")
        txt.insert("end", f"{status_icon} Step {agent.step_index}/{agent.step_total}\n", "heading")
        txt.insert("end", f"{agent.step_description}\n\n", "heading")

        for tc in agent.tool_calls:
            tag = "success" if tc.get("success", True) else "error"
            txt.insert("end", f"🔧 {tc.get('name', '?')}\n", "tool_name")
            args = tc.get("args", {})
            if args:
                txt.insert("end", f"   Args: {json.dumps(args, indent=2)[:300]}\n", "dim")
            result = tc.get("result", "")
            txt.insert("end", f"   → {str(result)[:500]}\n\n", tag)

        if agent.raw_output:
            txt.insert("end", "\n── Raw LLM Output ─────────────\n", "dim")
            txt.insert("end", agent.raw_output[:3000] + "\n", "raw")
        txt.config(state="disabled")

    def _update_agent_tab(self, tab_frame, agent):
        self._build_agent_content(tab_frame, agent)

    def open_plan_view(self, agents: list):
        key = "__plan__"
        if key in self._tabs:
            self.notebook.select(self._tabs[key])
            self._build_plan_content(self._tabs[key], agents)
            return
        f = Frame(self.notebook, bg="#1e1e1e")
        self._build_plan_content(f, agents)
        self.notebook.add(f, text=" 📋 Plan ")
        self.notebook.select(f)
        self._tabs[key] = f

    def _build_plan_content(self, parent, agents: list):
        for w in parent.winfo_children():
            w.destroy()
        txt = ScrolledText(parent, wrap="word", font=("Consolas", 12),
                           bg="#1e1e1e", fg="#d4d4d4", relief="flat",
                           padx=20, pady=20)
        txt.pack(fill="both", expand=True)
        txt.tag_config("title", foreground="#c084fc",
                       font=("Consolas", 16, "bold"))
        txt.tag_config("done", foreground="#34d399")
        txt.tag_config("running", foreground="#fbbf24")
        txt.tag_config("pending", foreground="#888888")
        txt.tag_config("error", foreground="#f87171")
        txt.insert("end", "📋 Current Plan\n", "title")
        txt.insert("end", "─" * 40 + "\n\n")
        for a in agents:
            icon = {"pending": "⬜", "running": "🔄",
                    "done": "✅", "error": "❌"}.get(a.status, "?")
            tag = a.status if a.status in ("done","running","pending","error") else "pending"
            txt.insert("end", f"{icon} {a.step_index}. {a.step_description}\n\n", tag)
        txt.config(state="disabled")

    def _on_right_click(self, event):
        tab_id = self.notebook.identify(event.x, event.y)
        if not tab_id:
            return
        try:
            idx = self.notebook.index(f"@{event.x},{event.y}")
            tab = self.notebook.nametowidget(self.notebook.tabs()[idx])
            keys_to_remove = [k for k, v in self._tabs.items() if v == tab]
            for k in keys_to_remove:
                del self._tabs[k]
            self.notebook.forget(idx)
        except Exception:
            pass

    def _apply_syntax(self, txt, ext):
        ext = ext.lower()
        kw_map = {
            ".py": (r'\b(def|class|import|from|return|if|else|elif|for|while|'
                    r'try|except|with|as|in|not|and|or|True|False|None|self|'
                    r'raise|yield|async|await|lambda|pass|break|continue)\b'),
            ".js": (r'\b(function|const|let|var|return|if|else|for|while|'
                    r'class|import|export|from|new|this|true|false|null|'
                    r'undefined|async|await|try|catch|throw)\b'),
        }
        pattern = kw_map.get(ext)
        if not pattern:
            return
        txt.tag_config("keyword", foreground="#569cd6")
        txt.tag_config("string", foreground="#ce9178")
        txt.tag_config("comment", foreground="#6a9955")
        content = txt.get("1.0", "end")
        for m in re.finditer(pattern, content):
            start = f"1.0+{m.start()}c"
            end = f"1.0+{m.end()}c"
            txt.tag_add("keyword", start, end)
        str_pat = r'(\"\"\".*?\"\"\"|\'\'\'.*?\'\'\'|\".*?\"|\'.*?\')'
        for m in re.finditer(str_pat, content, re.DOTALL):
            start = f"1.0+{m.start()}c"
            end = f"1.0+{m.end()}c"
            txt.tag_add("string", start, end)
        cmt = r'#.*$' if ext == ".py" else r'//.*$'
        for m in re.finditer(cmt, content, re.MULTILINE):
            start = f"1.0+{m.start()}c"
            end = f"1.0+{m.end()}c"
            txt.tag_add("comment", start, end)
