"""Command-line interface for resume-agent."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

from resume_agent import __version__
from resume_agent.agent import ResumeAgent
from resume_agent.compiler import open_file, tectonic_path
from resume_agent.library import Resume, ResumeLibrary


def _preflight() -> bool:
    """Check prerequisites; print friendly guidance if anything is missing."""
    ok = True
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ERROR: ANTHROPIC_API_KEY is not set.\n"
            "  Get a key at https://console.anthropic.com/ and run:\n"
            "    export ANTHROPIC_API_KEY=sk-ant-...\n"
            "  (or add it to a .env you source before running).",
            file=sys.stderr,
        )
        ok = False
    if tectonic_path() is None:
        print(
            "WARNING: Tectonic is not installed, so PDFs can't be compiled locally.\n"
            "  Install it with:  brew install tectonic\n"
            "  (the agent will still write LaTeX, but won't be able to verify it).",
            file=sys.stderr,
        )
    return ok


def _resolve_workspace(args) -> tuple[Path, Resume | None]:
    """Pick the working directory: a named library entry, or --workspace."""
    name = getattr(args, "name", None)
    if name:
        lib = ResumeLibrary()
        resume = lib.get_or_create(name)
        return resume.dir, resume
    return Path(getattr(args, "workspace", "./output")).expanduser(), None


def _gather_instruction(args) -> str:
    parts: list[str] = []
    if args.prompt:
        parts.append(args.prompt)
    if args.details:
        details = Path(args.details).expanduser()
        if not details.exists():
            print(f"ERROR: details file not found: {details}", file=sys.stderr)
            raise SystemExit(2)
        parts.append("Here are my details:\n\n" + details.read_text(encoding="utf-8"))
    if args.style:
        parts.append(f"Style/format: {args.style}.")
    if not parts:
        print("ERROR: provide a prompt and/or --details. Try `resume-agent build --help`.", file=sys.stderr)
        raise SystemExit(2)
    parts.append(
        "Build the document end to end and compile it to PDF (main.tex). "
        "If anything important is missing, use clear placeholders rather than inventing facts."
    )
    return "\n\n".join(parts)


def _finish(agent: ResumeAgent, resume: Resume | None, out: str | None, do_open: bool) -> None:
    if resume is not None:
        resume.touch()
    pdf = agent.ws.latest_pdf()
    if pdf is None:
        print("\nNo PDF was produced — check the messages above.", file=sys.stderr)
        return
    if out:
        dest = Path(out).expanduser().resolve()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf, dest)
        print(f"\nPDF: {dest}")
        pdf = dest
    else:
        print(f"\nPDF: {pdf}")
    if resume is not None:
        print(f"Saved as: {resume.name!r}  (resume-agent edit {resume.slug!r})")
    if do_open:
        open_file(pdf)


# -- commands ----------------------------------------------------------------


def cmd_build(args) -> int:
    if not _preflight():
        return 1
    instruction = _gather_instruction(args)
    workspace, resume = _resolve_workspace(args)
    agent = ResumeAgent(workspace)
    if resume:
        print(f"Saved resume: {resume.name!r}  ({agent.ws.root})\n")
    else:
        print(f"Workspace: {agent.ws.root}\n")
    if resume and (agent.ws.root / "main.tex").exists():
        instruction = (
            "There is an existing main.tex in the workspace — read it first, then apply this:\n\n"
            + instruction
        )
    agent.run_turn(instruction)
    _finish(agent, resume, args.out, args.open)
    return 0


def cmd_edit(args) -> int:
    """Open an interactive session on a saved resume (continue editing it)."""
    if not _preflight():
        return 1
    lib = ResumeLibrary()
    resume = lib.get(args.name)
    if resume is None:
        print(f"No saved resume named {args.name!r}. See `resume-agent list`.", file=sys.stderr)
        return 2
    return _chat_loop(ResumeAgent(resume.dir), resume)


def cmd_chat(args) -> int:
    if not _preflight():
        return 1
    workspace, resume = _resolve_workspace(args)
    return _chat_loop(ResumeAgent(workspace), resume)


def _chat_loop(agent: ResumeAgent, resume: Resume | None) -> int:
    label = f"{resume.name!r} — {agent.ws.root}" if resume else str(agent.ws.root)
    print(f"Workspace: {label}")
    has_existing = (agent.ws.root / "main.tex").exists()
    print(
        "resume-agent chat — describe what you want and refine it as you go.\n"
        "Commands: /open  /files  /rename <new name>  /exit"
        + ("\n(An existing resume is loaded — just tell me what to change.)\n" if has_existing else "\n")
    )
    while True:
        try:
            line = input("you › ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("/exit", "/quit", "/q"):
            break
        if line == "/open":
            pdf = agent.ws.latest_pdf()
            print(f"  opened {pdf}" if pdf and open_file(pdf) else "  no PDF to open yet")
            continue
        if line == "/files":
            print(agent.ws.list_files())
            continue
        if line.startswith("/rename "):
            new = line[len("/rename "):].strip()
            if not new:
                print("  usage: /rename <new name>")
            elif resume is None:
                print("  this session isn't a saved resume; start with `resume-agent chat --name <name>`")
            else:
                ResumeLibrary().rename(resume.name, new)
                resume.name = new
                print(f"  renamed to {new!r}")
            continue
        prompt = line
        if has_existing:
            prompt = "Read the current main.tex first if you haven't, then: " + line
            has_existing = False  # only nudge once
        agent.run_turn(prompt)
        if resume is not None:
            resume.touch()
    return 0


def cmd_list(args) -> int:
    resumes = ResumeLibrary().list()
    if not resumes:
        print("No saved resumes yet. Create one with: resume-agent build --name \"My Resume\" ...")
        return 0
    print(f"{'NAME':<32}  {'UPDATED':<20}  PDF   SLUG")
    for r in resumes:
        updated = time.strftime("%Y-%m-%d %H:%M", time.localtime(r.updated))
        print(f"{r.name[:32]:<32}  {updated:<20}  {'yes' if r.pdf else ' no':<3}  {r.slug}")
    return 0


def cmd_rename(args) -> int:
    try:
        r = ResumeLibrary().rename(args.old, args.new)
    except KeyError:
        print(f"No saved resume named {args.old!r}. See `resume-agent list`.", file=sys.stderr)
        return 2
    print(f"Renamed to {r.name!r}.")
    return 0


def cmd_delete(args) -> int:
    if ResumeLibrary().delete(args.name):
        print(f"Deleted {args.name!r}.")
        return 0
    print(f"No saved resume named {args.name!r}.", file=sys.stderr)
    return 2


def cmd_open(args) -> int:
    resume = ResumeLibrary().get(args.name)
    if resume is None:
        print(f"No saved resume named {args.name!r}.", file=sys.stderr)
        return 2
    pdf = resume.pdf
    if pdf and open_file(pdf):
        print(f"Opened {pdf}")
        return 0
    print("No compiled PDF for that resume yet.", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="resume-agent",
        description="Prompt-driven LaTeX resume builder powered by Claude + Tectonic.",
    )
    parser.add_argument("--version", action="version", version=f"resume-agent {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-w", "--workspace", default="./output",
        help="Directory to work in when not using --name (default: ./output).",
    )
    common.add_argument(
        "-n", "--name",
        help="Save/continue under this name in your resume library (editable later).",
    )

    b = sub.add_parser("build", parents=[common], help="Build a document in one shot from details/a prompt.")
    b.add_argument("prompt", nargs="?", help="Free-text description, e.g. \"resume for a backend engineer named ...\".")
    b.add_argument("-d", "--details", help="Path to a file with your details (markdown/plain text).")
    b.add_argument("-s", "--style", help="Desired style/format, e.g. 'modern single-column', 'academic CV', 'two-column with a teal accent'.")
    b.add_argument("-o", "--out", help="Copy the finished PDF to this path.")
    b.add_argument("--open", action="store_true", help="Open the PDF when done.")
    b.set_defaults(func=cmd_build)

    c = sub.add_parser("chat", parents=[common], help="Interactive session — build and refine conversationally.")
    c.set_defaults(func=cmd_chat)

    e = sub.add_parser("edit", help="Continue editing a saved resume interactively.")
    e.add_argument("name", help="Name or slug of the saved resume.")
    e.set_defaults(func=cmd_edit)

    sub.add_parser("list", help="List saved resumes in your library.").set_defaults(func=cmd_list)

    rn = sub.add_parser("rename", help="Rename a saved resume.")
    rn.add_argument("old", help="Current name or slug.")
    rn.add_argument("new", help="New name.")
    rn.set_defaults(func=cmd_rename)

    dl = sub.add_parser("delete", help="Delete a saved resume.")
    dl.add_argument("name", help="Name or slug to delete.")
    dl.set_defaults(func=cmd_delete)

    op = sub.add_parser("open", help="Open a saved resume's PDF.")
    op.add_argument("name", help="Name or slug to open.")
    op.set_defaults(func=cmd_open)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
    except _anthropic_error() as exc:
        print(f"\nAPI error: {exc}", file=sys.stderr)
        return 1


def _anthropic_error():
    """Return the anthropic base error class (lazy import keeps --help fast)."""
    try:
        import anthropic

        return anthropic.APIError
    except Exception:  # pragma: no cover
        return Exception


if __name__ == "__main__":
    raise SystemExit(main())
