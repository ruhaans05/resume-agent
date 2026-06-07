"""Workspace + tool definitions the agent uses to author and compile LaTeX."""

from __future__ import annotations

import json
from pathlib import Path

from resume_agent.compiler import CompileResult, compile_tex

_MAX_LOG = 3500


class Workspace:
    """A sandboxed directory the agent reads/writes/compiles within.

    All file operations are confined to ``root`` — paths that escape it are
    rejected, so the agent can never touch files elsewhere on disk.
    """

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise ValueError(f"Path escapes the workspace: {rel}")
        return p

    def write_file(self, path: str, content: str) -> str:
        p = self._resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"Wrote {path} ({len(content)} bytes)."

    def read_file(self, path: str) -> str:
        p = self._resolve(path)
        if not p.exists():
            return f"(file does not exist: {path})"
        return p.read_text(encoding="utf-8")

    def list_files(self) -> str:
        files = sorted(
            str(p.relative_to(self.root))
            for p in self.root.rglob("*")
            if p.is_file()
        )
        return "\n".join(files) if files else "(workspace is empty)"

    def compile(self, main_file: str = "main.tex") -> CompileResult:
        return compile_tex(self._resolve(main_file))

    def latest_pdf(self) -> Path | None:
        pdfs = list(self.root.rglob("*.pdf"))
        if not pdfs:
            return None
        return max(pdfs, key=lambda p: p.stat().st_mtime)


# ---- Tool schemas exposed to Claude ----------------------------------------

TOOLS = [
    {
        "name": "write_file",
        "description": (
            "Create or overwrite a file in the workspace. Use this to write the "
            "LaTeX source (default the main document to 'main.tex'). Pass the full "
            "file contents every time — this replaces the file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the workspace, e.g. 'main.tex'."},
                "content": {"type": "string", "description": "The complete file contents."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "read_file",
        "description": "Read a file from the workspace (e.g. to review the current LaTeX before editing it).",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path relative to the workspace."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "list_files",
        "description": "List all files currently in the workspace.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "compile_latex",
        "description": (
            "Compile a LaTeX file to PDF with Tectonic. Returns whether it "
            "succeeded and, on failure, the error log so you can fix the source "
            "and recompile. Always compile before telling the user you are done."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "main_file": {
                    "type": "string",
                    "description": "The .tex file to compile. Defaults to 'main.tex'.",
                },
            },
        },
    },
]


def execute_tool(ws: Workspace, name: str, tool_input: dict) -> tuple[str, bool]:
    """Run a tool call. Returns (result_text, is_error)."""
    try:
        if name == "write_file":
            return ws.write_file(tool_input["path"], tool_input["content"]), False
        if name == "read_file":
            return ws.read_file(tool_input["path"]), False
        if name == "list_files":
            return ws.list_files(), False
        if name == "compile_latex":
            result = ws.compile(tool_input.get("main_file", "main.tex"))
            log = result.log[:_MAX_LOG]
            if result.ok:
                rel = result.pdf_path.relative_to(ws.root) if result.pdf_path else "?"
                return f"Compilation succeeded. PDF written to {rel}.\n\n{log}", False
            return f"Compilation FAILED. Fix the LaTeX and recompile.\n\n{log}", True
        return f"Unknown tool: {name}", True
    except Exception as exc:  # surface the error to the model so it can recover
        return f"Tool '{name}' raised an error: {exc}", True


def tool_result_block(tool_use_id: str, text: str, is_error: bool) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": text,
        "is_error": is_error,
    }
