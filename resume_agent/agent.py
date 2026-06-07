"""The resume-building agent: a Claude-driven tool loop over a LaTeX workspace."""

from __future__ import annotations

import sys
from pathlib import Path

import anthropic

from resume_agent.tools import (
    TOOLS,
    Workspace,
    execute_tool,
    tool_result_block,
)

MODEL = "claude-opus-4-8"

SYSTEM_PROMPT = """\
You are resume-agent, an expert LaTeX typesetter and resume writer. You build
polished, professional documents — resumes, CVs, and cover letters — in whatever
format and style the user wants, and you compile them to PDF.

Your workspace is a directory you control through tools:
- write_file / read_file / list_files to manage the LaTeX source
- compile_latex to build the PDF with the Tectonic engine

Hard rules:
- The main document is always 'main.tex'. Keep everything compilable from it.
- ALWAYS run compile_latex before you tell the user the document is ready. If it
  fails, read the error log, fix the LaTeX, and recompile. Never hand back a
  document that does not compile.
- The compiler is Tectonic (XeTeX-based), so fontspec and system fonts work, and
  packages download automatically on first use.

How to work:
- If the user gives you their details (experience, education, skills, contact),
  write the whole document for them in the requested style. If they didn't name a
  style, choose a clean, modern, single-column layout that reads well on one page.
- If the user is giving instructions incrementally, treat it as a conversation:
  make the requested change, recompile, and briefly say what you did. Read the
  current main.tex first when editing so you build on what's there.
- Match whatever format the user asks for — single vs. two column, classic vs.
  modern, academic CV, with or without a photo, specific color, a particular
  section order, a named template look, etc. The user is in charge of the format.

Integrity:
- Never invent employment history, degrees, dates, or credentials. If the user
  wants a template and hasn't given real details, use clear placeholders like
  [Company Name] or [you@email.com] and tell them what to fill in.

Style of your replies:
- Be concise. A sentence or two between actions is plenty. Don't paste the full
  LaTeX back to the user — it's already in the file. When done, tell them the
  file is compiled and where the PDF is.
"""


class ResumeAgent:
    def __init__(self, workspace: Path | str, model: str = MODEL, max_tokens: int = 16000):
        self.client = anthropic.Anthropic()
        self.ws = Workspace(workspace)
        self.model = model
        self.max_tokens = max_tokens
        self.messages: list[dict] = []

    # -- Claude request, with graceful degradation across SDK versions --------

    def _base_kwargs(self) -> dict:
        return dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=self.messages,
            thinking={"type": "adaptive"},
        )

    def _final_message(self):
        base = self._base_kwargs()
        # Prefer high effort + adaptive thinking; fall back if the installed SDK
        # is older and doesn't accept these parameters.
        attempts = [
            dict(base, output_config={"effort": "high"}),
            base,
            {k: v for k, v in base.items() if k != "thinking"},
        ]
        last_exc: Exception | None = None
        for kwargs in attempts:
            try:
                return self._run_stream(kwargs)
            except TypeError as exc:
                last_exc = exc
                continue
        raise last_exc  # type: ignore[misc]

    def _run_stream(self, kwargs: dict):
        printed = False
        with self.client.messages.stream(**kwargs) as stream:
            for event in stream:
                if event.type == "content_block_delta" and event.delta.type == "text_delta":
                    sys.stdout.write(event.delta.text)
                    sys.stdout.flush()
                    printed = True
            message = stream.get_final_message()
        if printed:
            print()
        return message

    # -- The agentic loop ------------------------------------------------------

    def run_turn(self, user_text: str) -> None:
        """Send one user message and run the tool loop until Claude is done."""
        self.messages.append({"role": "user", "content": user_text})

        while True:
            message = self._final_message()
            self.messages.append({"role": "assistant", "content": message.content})

            if message.stop_reason != "tool_use":
                break

            tool_results = []
            for block in message.content:
                if block.type != "tool_use":
                    continue
                self._announce(block.name, block.input)
                text, is_error = execute_tool(self.ws, block.name, dict(block.input))
                tool_results.append(tool_result_block(block.id, text, is_error))

            self.messages.append({"role": "user", "content": tool_results})

    @staticmethod
    def _announce(name: str, tool_input: dict) -> None:
        if name == "write_file":
            print(f"  \033[2m→ writing {tool_input.get('path', '?')}\033[0m")
        elif name == "read_file":
            print(f"  \033[2m→ reading {tool_input.get('path', '?')}\033[0m")
        elif name == "list_files":
            print("  \033[2m→ listing files\033[0m")
        elif name == "compile_latex":
            print(f"  \033[2m→ compiling {tool_input.get('main_file', 'main.tex')}\033[0m")
