"""GUI — AI Code Assistant (3-panel: File Browser | Viewer | Chat)."""
import json, sys, threading, uuid
from pathlib import Path

if sys.platform == "win32":
    try:
        from ctypes import windll; windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            from ctypes import windll; windll.user32.SetProcessDPIAware()
        except Exception: pass

from tkinter import (Tk, Toplevel, Frame, Button, Label, Entry, Text,
                     StringVar, BooleanVar, Checkbutton, messagebox, ttk)
from tkinter.scrolledtext import ScrolledText
from tkinter import filedialog

import config
from tools import TOOL_DEFINITIONS, execute_tool, cleanup_processes
import settings as user_settings
from llm_client import run_pipeline
from gui_panels import FileBrowserPanel, TabbedViewerPanel, AgentExecution


class AICodeAssistantGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Code Assistant")
        self.root.geometry("1600x950")
        self.root.configure(bg="#0c0c0c")
        self.root.minsize(1200, 700)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.conversation_history = []
        self.is_processing = False
        self.settings = user_settings.load_settings()
        self.current_chat_id = str(uuid.uuid4())
        self.agent_executions: list[AgentExecution] = []
        self._cancel = False
        self._chat_maximized = False

        self._setup_ui()
        self._refresh_chat_list()

    # ── Close ────────────────────────────────────────────────────────
    def _on_close(self):
        self._cancel = True
        cleanup_processes()
        self.root.destroy()

    # ── UI Layout ────────────────────────────────────────────────────
    def _setup_ui(self):
        self._build_header()
        self._build_content()
        self._build_status_bar()
        self._show_welcome()

    def _build_header(self):
        h = Frame(self.root, bg="#252526", height=52)
        h.pack(fill="x"); h.pack_propagate(False)
        Label(h, text="⚡ AI Code Assistant", font=("Segoe UI", 15, "bold"),
              bg="#252526", fg="#ffffff").pack(side="left", padx=16, pady=12)
        # Right-side controls
        rf = Frame(h, bg="#252526"); rf.pack(side="right", padx=12, pady=10)
        for txt, cmd in [("📋 Plan", self._open_plan_tab),
                         ("⚙ Settings", self._open_settings),
                         ("📁 Workspace", self._change_workspace)]:
            Button(rf, text=txt, font=("Segoe UI", 9), bg="#3c3c3c",
                   fg="#ffffff", relief="flat", padx=10, pady=4,
                   command=cmd, cursor="hand2").pack(side="left", padx=3)
        self.workspace_label = Label(rf, font=("Segoe UI", 9),
              bg="#252526", fg="#888888",
              text=str(config.WORKSPACE_PATH.resolve())[-40:])
        self.workspace_label.pack(side="left", padx=(10,0))

    def _build_content(self):
        self.content = Frame(self.root, bg="#0c0c0c")
        self.content.pack(fill="both", expand=True)
        # Sash panes: file browser | viewer | chat
        self.panes = ttk.PanedWindow(self.content, orient="horizontal")
        self.panes.pack(fill="both", expand=True)
        # Left: file browser
        self.file_browser = FileBrowserPanel(
            self.panes, on_file_open=self._open_file_in_viewer, width=220)
        self.panes.add(self.file_browser, weight=0)
        # Middle: tabbed viewer
        self.viewer = TabbedViewerPanel(self.panes)
        self.panes.add(self.viewer, weight=3)
        # Right: chat panel
        self._chat_frame = self._build_chat_panel(self.panes)
        self.panes.add(self._chat_frame, weight=1)

    def _build_chat_panel(self, parent):
        cf = Frame(parent, bg="#141414", width=380)
        cf.pack_propagate(False)
        # Chat list header
        top = Frame(cf, bg="#1e1e1e"); top.pack(fill="x")
        Label(top, text="CHATS", font=("Segoe UI", 8, "bold"),
              bg="#1e1e1e", fg="#888888").pack(side="left", padx=10, pady=5)
        Button(top, text="+ New", font=("Segoe UI", 8), bg="#007acc",
               fg="#fff", relief="flat", padx=6, pady=2,
               command=self._new_chat, cursor="hand2").pack(side="left", padx=4)
        self.maximize_btn = Button(top, text="⛶", font=("Segoe UI", 11), bg="#1e1e1e",
               fg="#888", relief="flat", bd=0,
               command=self._toggle_maximize_chat,
               cursor="hand2")
        self.maximize_btn.pack(side="right", padx=6)
        from tkinter import Listbox
        self.chat_listbox = Listbox(cf, bg="#1e1e1e", fg="#cccccc",
            selectbackground="#37373d", selectforeground="#fff",
            font=("Segoe UI", 9), relief="flat", highlightthickness=0,
            bd=0, height=5)
        self.chat_listbox.pack(fill="x", padx=6, pady=(0,0))
        self.chat_listbox.bind("<<ListboxSelect>>", self._on_chat_select)
        self.chat_listbox.bind("<Delete>", self._on_chat_delete)
        Label(cf, text="Press Del to delete selected chat", font=("Segoe UI", 7),
              bg="#141414", fg="#555555").pack(anchor="e", padx=10, pady=(0,4))
        # Separator
        Frame(cf, bg="#333333", height=1).pack(fill="x")
        # Chat display
        self.chat_display = ScrolledText(
            cf, wrap="word", font=("Consolas", 11),
            bg="#141414", fg="#f0f0f0", insertbackground="#fff",
            selectbackground="#264f78", relief="flat", padx=14, pady=14)
        self.chat_display.pack(fill="both", expand=True)
        self.chat_display.config(state="disabled")
        for tag, fg, kw in [
            ("user",       "#7dd3fc", {"font":("Consolas",11,"bold")}),
            ("assistant",  "#fef08a", {}),
            ("phase",      "#c084fc", {"font":("Consolas",11,"bold")}),
            ("plan",       "#a5f3fc", {"font":("Consolas",10)}),
            ("step",       "#86efac", {"font":("Consolas",10,"italic")}),
            ("step_link",  "#86efac", {"font":("Consolas",10,"italic"),
                                       "underline":True}),
            ("tool_run",   "#fbbf24", {"font":("Consolas",10,"italic")}),
            ("tool_ok",    "#34d399", {"font":("Consolas",10)}),
            ("tool_err",   "#f87171", {"font":("Consolas",10)}),
            ("error",      "#f87171", {}),
            ("debug_ok",   "#4ade80", {"font":("Consolas",11,"bold")}),
            ("debug_fail", "#fb923c", {"font":("Consolas",11,"bold")}),
        ]:
            self.chat_display.tag_config(tag, foreground=fg, **kw)
        self.chat_display.tag_bind("step_link", "<Button-1>", self._on_step_click)
        self.chat_display.tag_bind("step_link", "<Enter>",
            lambda e: self.chat_display.config(cursor="hand2"))
        self.chat_display.tag_bind("step_link", "<Leave>",
            lambda e: self.chat_display.config(cursor=""))
        # Input
        inp = Frame(cf, bg="#141414"); inp.pack(fill="x", padx=8, pady=8)
        self.input_field = Text(inp, font=("Segoe UI", 12), bg="#262626",
            fg="#f5f5f5", insertbackground="#fff", relief="flat",
            bd=0, height=3, wrap="word", padx=8, pady=8)
        self.input_field.pack(side="left", fill="x", expand=True)
        self.input_field.bind("<Return>", lambda e: (self._send(), "break")[1])
        self.input_field.bind("<Shift-Return>",
            lambda e: (self.input_field.insert("insert","\n"), "break")[1])
        Button(inp, text="Send", font=("Segoe UI", 11, "bold"),
               bg="#007acc", fg="#fff", activebackground="#005a9e",
               relief="flat", padx=18, pady=10,
               command=self._send, cursor="hand2").pack(side="right", padx=(6,0))
        self.status_lbl = Label(cf, text="", font=("Segoe UI", 9, "italic"),
                                bg="#141414", fg="#93c5fd")
        self.status_lbl.pack(fill="x", padx=10, pady=(0,4))
        self.input_field.focus()
        return cf

    def _build_status_bar(self):
        sb = Frame(self.root, bg="#007acc", height=22)
        sb.pack(fill="x", side="bottom"); sb.pack_propagate(False)
        self.statusbar_label = Label(sb, text="Ready", font=("Segoe UI", 8),
              bg="#007acc", fg="#ffffff")
        self.statusbar_label.pack(side="left", padx=10)

    # ── Maximize Chat ────────────────────────────────────────────────
    def _toggle_maximize_chat(self):
        if not self._chat_maximized:
            self.panes.pack_forget()
            self._chat_frame.pack(fill="both", expand=True, in_=self.content)
            self._chat_maximized = True
            self.maximize_btn.config(text="⮌ Go Back", font=("Segoe UI", 9))
        else:
            self._chat_frame.pack_forget()
            self.panes.pack(fill="both", expand=True)
            self.panes.add(self._chat_frame, weight=1)
            self._chat_maximized = False
            self.maximize_btn.config(text="⛶", font=("Segoe UI", 11))

    # ── File / Agent Viewer ──────────────────────────────────────────
    def _open_file_in_viewer(self, path: Path):
        self.viewer.open_file(path)
        self._set_status(f"Opened {path.name}")

    def _open_plan_tab(self):
        self.viewer.open_plan_view(self.agent_executions)

    def _on_step_click(self, event):
        idx = self.chat_display.tag_prevrange(
            "step_link", self.chat_display.index(f"@{event.x},{event.y}"))
        if not idx:
            return
        text = self.chat_display.get(idx[0], idx[1])
        # parse step index from "[1/3]" prefix
        import re
        m = re.match(r'\s*\[(\d+)/', text)
        if m:
            n = int(m.group(1))
            agents = [a for a in self.agent_executions if a.step_index == n]
            if agents:
                self.viewer.open_agent_view(agents[0])

    # ── Settings ─────────────────────────────────────────────────────
    def _open_settings(self):
        win = Toplevel(self.root)
        win.title("Settings"); win.geometry("440x440")
        win.configure(bg="#1e1e1e"); win.grab_set()
        win.transient(self.root)
        pad = 16; row = 0
        Label(win, text="Settings", font=("Segoe UI",14,"bold"),
              bg="#1e1e1e", fg="#fff").grid(row=row, column=0, sticky="w",
              padx=pad, pady=pad); row+=1

        try:
            import ollama
            models_info = ollama.list()
            if hasattr(models_info, 'models'):
                available_models = [m.model for m in models_info.models]
            elif isinstance(models_info, dict) and "models" in models_info:
                available_models = [m["name"] for m in models_info["models"]]
            else:
                available_models = []
        except Exception:
            available_models = []
        
        if not available_models:
            available_models = ["gemma4:12b", "qwen2.5-coder:14b"]

        planner_var = StringVar(value=self.settings.get("planner_model","gemma4:12b"))
        coder_var = StringVar(value=self.settings.get("coder_model","qwen2.5-coder:14b"))

        Label(win, text="Planner Model:", font=("Segoe UI",10),
              bg="#1e1e1e", fg="#e0e0e0").grid(row=row, column=0, sticky="w", padx=pad, pady=(4,0)); row+=1
        planner_cb = ttk.Combobox(win, textvariable=planner_var, values=available_models, state="readonly", width=35)
        planner_cb.grid(row=row, column=0, sticky="w", padx=pad, pady=(0,8)); row+=1

        Label(win, text="Coder Model:", font=("Segoe UI",10),
              bg="#1e1e1e", fg="#e0e0e0").grid(row=row, column=0, sticky="w", padx=pad, pady=(4,0)); row+=1
        coder_cb = ttk.Combobox(win, textvariable=coder_var, values=available_models, state="readonly", width=35)
        coder_cb.grid(row=row, column=0, sticky="w", padx=pad, pady=(0,12)); row+=1

        plan_var = BooleanVar(value=self.settings.get("task_planning_enabled",True))
        auto_var = BooleanVar(value=self.settings.get("planning_auto_detect",True))
        turns_var = StringVar(value=str(self.settings.get("max_history_turns",20)))
        for text, var in [("Enable Task Planning (Gemma 4)", plan_var),
                          ("Auto-detect complexity", auto_var)]:
            Checkbutton(win, text=text, variable=var, font=("Segoe UI",10),
                bg="#1e1e1e", fg="#e0e0e0", selectcolor="#2d2d2d",
                activebackground="#1e1e1e", activeforeground="#e0e0e0"
            ).grid(row=row, column=0, sticky="w", padx=pad, pady=2); row+=1
        Label(win, text="Max History Turns:", font=("Segoe UI",10),
              bg="#1e1e1e", fg="#e0e0e0").grid(row=row, column=0, sticky="w",
              padx=pad, pady=(12,2)); row+=1
        Entry(win, textvariable=turns_var, width=8, font=("Segoe UI",10),
              bg="#2d2d2d", fg="#fff", insertbackground="#fff",
              relief="flat").grid(row=row, column=0, sticky="w",
              padx=pad, pady=(0,12), ipady=4); row+=1
        def save():
            try:
                t = int(turns_var.get())
                assert t > 0
            except Exception:
                messagebox.showerror("Error","Max turns must be a positive integer.")
                return
            s = self.settings.copy()
            s.update(planner_model=planner_var.get(),
                     coder_model=coder_var.get(),
                     task_planning_enabled=plan_var.get(),
                     planning_auto_detect=auto_var.get(),
                     max_history_turns=t)
            user_settings.save_settings(s)
            self.settings = user_settings.load_settings()
            win.destroy()
        bf = Frame(win, bg="#1e1e1e")
        bf.grid(row=row, column=0, sticky="w", padx=pad, pady=12)
        Button(bf, text="Save", font=("Segoe UI",10), bg="#007acc",
               fg="#fff", relief="flat", padx=20, pady=6,
               command=save, cursor="hand2").pack(side="left")
        Button(bf, text="Cancel", font=("Segoe UI",10), bg="#3c3c3c",
               fg="#fff", relief="flat", padx=20, pady=6,
               command=win.destroy, cursor="hand2").pack(side="left", padx=(8,0))

    # ── Workspace ────────────────────────────────────────────────────
    def _change_workspace(self):
        folder = filedialog.askdirectory(title="Select Workspace",
                    initialdir=str(config.WORKSPACE_PATH))
        if folder:
            config.WORKSPACE_PATH = Path(folder).resolve()
            self.workspace_label.config(
                text=str(config.WORKSPACE_PATH)[-40:])
            self.file_browser.refresh()
            self._append(f"Workspace → {config.WORKSPACE_PATH}\n\n","tool_ok")

    # ── Chat Display ─────────────────────────────────────────────────
    def _append(self, text, tag="assistant"):
        self.chat_display.config(state="normal")
        self.chat_display.insert("end", text, tag)
        self.chat_display.see("end")
        self.chat_display.config(state="disabled")

    def _add_msg(self, role, content, tag=None):
        prefix = {"user":"You: ","assistant":"Assistant: "}.get(role,"")
        tag = tag or {"user":"user","assistant":"assistant"}.get(role,"assistant")
        self._append(prefix, tag); self._append(content+"\n\n", tag)

    def _show_welcome(self):
        p = self.settings.get("planner_model","gemma4:12b")
        c = self.settings.get("coder_model","qwen3-coder:30b")
        self._add_msg("assistant",
            f"Welcome!\n\n🧠 Planner: {p}\n⚡ Coder:   {c}\n\n"
            "Ask me anything. Click steps in the chat to inspect agents.")

    def _set_status(self, text):
        self.status_lbl.config(text=text)
        self.statusbar_label.config(text=text)

    # ── Chat Persistence ─────────────────────────────────────────────
    def _chats_dir(self):
        d = Path(__file__).parent/"chats"; d.mkdir(exist_ok=True); return d

    def _new_chat(self):
        if self.is_processing: return
        self.conversation_history = []
        self.agent_executions = []
        self.current_chat_id = str(uuid.uuid4())
        self.chat_display.config(state="normal")
        self.chat_display.delete("1.0","end")
        self.chat_display.config(state="disabled")
        self._show_welcome(); self._refresh_chat_list()

    def _save_chat(self):
        if not self.conversation_history: return
        title = "New Chat"
        for m in self.conversation_history:
            if m.get("role")=="user":
                title = m.get("content","")[:30].strip()+"..."; break
        p = self._chats_dir()/f"{self.current_chat_id}.json"
        p.write_text(json.dumps({"id":self.current_chat_id,
            "title":title,"history":self.conversation_history},indent=2),
            encoding="utf-8")
        self._refresh_chat_list()

    def _refresh_chat_list(self):
        if not hasattr(self,"chat_listbox"): return
        self.chat_listbox.delete(0,"end"); self.chat_files=[]
        for p in sorted(self._chats_dir().glob("*.json"),
                        key=lambda x:x.stat().st_mtime, reverse=True):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                self.chat_listbox.insert("end", d.get("title","?"))
                self.chat_files.append(p)
            except Exception: pass

    def _on_chat_delete(self, event):
        if self.is_processing: return
        sel = self.chat_listbox.curselection()
        if not sel: return
        if messagebox.askyesno("Delete Chat", "Delete this chat history?"):
            try:
                self.chat_files[sel[0]].unlink()
                self._refresh_chat_list()
                self._new_chat()
            except Exception as e:
                messagebox.showerror("Error", f"Could not delete chat: {e}")

    def _on_chat_select(self, event):
        if self.is_processing: return
        sel = self.chat_listbox.curselection()
        if not sel: return
        try:
            d = json.loads(self.chat_files[sel[0]].read_text(encoding="utf-8"))
            self.current_chat_id = d["id"]
            self.conversation_history = d["history"]
            self.chat_display.config(state="normal")
            self.chat_display.delete("1.0","end")
            self.chat_display.config(state="disabled")
            self._show_welcome()
            for m in self.conversation_history:
                if m.get("role") in ("user","assistant"):
                    self._add_msg(m["role"], m.get("content",""))
        except Exception as e:
            messagebox.showerror("Error",f"Could not load chat: {e}")

    # ── Send / Pipeline ──────────────────────────────────────────────
    def _send(self):
        txt = self.input_field.get("1.0","end-1c").strip()
        if not txt or self.is_processing: return
        self.input_field.delete("1.0","end")
        self._add_msg("user", txt)
        self.is_processing = True; self._cancel = False
        self.agent_executions = []
        self.input_field.config(state="disabled")
        self._set_status("🧠 Planning...")
        threading.Thread(target=self._run_pipeline, args=(txt,),
                         daemon=True).start()

    def _run_pipeline(self, msg):
        self.settings = user_settings.load_settings()
        self.conversation_history.append({"role":"user","content":msg})
        self.root.after(0, self._save_chat)
        try:
            summary = run_pipeline(
                user_request=msg,
                conversation_history=self.conversation_history,
                planner_model=self.settings.get("planner_model","gemma4:12b"),
                coder_model=self.settings.get("coder_model","qwen3-coder:30b"),
                tools=TOOL_DEFINITIONS, execute_tool_fn=execute_tool,
                max_history_turns=self.settings.get("max_history_turns",20),
                use_planner=self.settings.get("task_planning_enabled",True),
                auto_detect_complexity=self.settings.get("planning_auto_detect",True),
                on_phase=self._cb_phase, on_plan_ready=self._cb_plan,
                on_step_start=self._cb_step_start, on_step_done=self._cb_step_done,
                on_tool_call=self._cb_tool_call, on_tool_result=self._cb_tool_result,
                on_debug_start=self._cb_debug_start, on_debug_done=self._cb_debug_done,
            )
            self.conversation_history.append({"role":"assistant","content":summary})
            self.root.after(0, self._save_chat)
            self.root.after(0, self._on_done, summary)
        except Exception as exc:
            self.root.after(0, self._on_error, str(exc))

    # ── Pipeline Callbacks ───────────────────────────────────────────
    def _cb_phase(self, phase, msg):
        self.root.after(0, self._append, f"\n{msg}\n", "phase")
        self.root.after(0, self._set_status, msg)

    def _cb_plan(self, steps):
        def show():
            self._append("Plan:\n","phase")
            for i,s in enumerate(steps,1):
                self._append(f"  {i}. {s}\n","plan")
            self._append("\n","plan")
        self.root.after(0, show)

    def _cb_step_start(self, idx, total, step):
        ae = AgentExecution(idx, total, step, status="running")
        self.agent_executions.append(ae)
        def show():
            self._append(f"  [{idx}/{total}] {step}\n", "step_link")
        self.root.after(0, show)

    def _cb_step_done(self, idx, total, result):
        import re
        for ae in self.agent_executions:
            if ae.step_index == idx:
                ae.status = "done"
                ae.raw_output = result or ""
                break
        clean = re.sub(r"<function=.*?(?:</function>|$)","",
                       result or "", flags=re.DOTALL).strip()
        short = (clean[:800]+"...") if len(clean)>800 else clean
        self.root.after(0, self._append,
            f"    → {short}\n\n" if short else "    → Done.\n\n", "tool_ok")

    def _cb_tool_call(self, name, args):
        # Attach to current running agent
        for ae in reversed(self.agent_executions):
            if ae.status == "running":
                ae.tool_calls.append({"name":name,"args":args})
                break
        self.root.after(0, self._append, f"    🔧 {name}...\n","tool_run")

    def _cb_tool_result(self, name, result, success):
        for ae in reversed(self.agent_executions):
            if ae.status == "running":
                tc = next((t for t in reversed(ae.tool_calls)
                           if t.get("name")==name and "result" not in t), None)
                if tc: tc.update(result=result, success=success)
                break
        tag = "tool_ok" if success else "tool_err"
        self.root.after(0, self._append,
            f"      → {str(result)[:200]}\n", tag)

    def _cb_debug_start(self, cmd):
        self.root.after(0, self._append, f"\n🔄 Debug: `{cmd}`\n","phase")

    def _cb_debug_done(self, success, log):
        icon = "✅" if success else "⚠️"
        tag = "debug_ok" if success else "debug_fail"
        self.root.after(0, self._append,
            f"{icon} Build {'succeeded' if success else 'failed'}.\n\n", tag)

    def _on_done(self, summary):
        self.is_processing = False
        self.input_field.config(state="normal"); self.input_field.focus()
        self._set_status("Ready")
        self._add_msg("assistant","Done. Click any step above to inspect the agent.")

    def _on_error(self, err):
        self.is_processing = False
        self.input_field.config(state="normal")
        self._add_msg("assistant", f"Error: {err}", "error")
        self._set_status("Error")


def main():
    root = Tk()
    AICodeAssistantGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
