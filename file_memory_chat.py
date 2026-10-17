"""HW6 Part 4 - chat with file-based memory (AGENT.md + MEMORY.md).

    python file_memory_chat.py

Commands: /memory  /compact  /dream  /help  /exit
Every turn rebuilds the system prompt from AGENT.md and MEMORY.md, so changes
made by /dream or by editing the files take effect immediately. At start-up
the program checks whether MEMORY.md must be consolidated (more than 40 lines,
or last consolidated more than 24 hours ago) and consolidates it if so.
"""
import os
import shutil
from datetime import datetime, timezone
from typing import Dict, List

from file_memory.consolidate import consolidate, format_report
from file_memory.dream import dream
from file_memory.memory_files import (AGENT_PATH, MEMORY_PATH, build_system_prompt,
                                      count_memory_lines, load_agent_md, load_memory_md,
                                      needs_consolidation, read_last_consolidated,
                                      write_memory_md)
from src.model_client import complete

MODEL = os.getenv("CHAT_MODEL", "qwen3:1.7b")
KEEP_RECENT = 2          # /compact keeps this many recent messages word for word

HELP = """Commands:
  /memory   show MEMORY.md, its line count, last consolidation and whether consolidation is due
  /compact  consolidate MEMORY.md (merge duplicates, resolve contradictions) and compact this
            conversation (older messages -> one summary); reports counts before and after
  /dream    find durable facts in this conversation and add them to MEMORY.md
  /help     show this help
  /exit     quit (MEMORY.md is a file, so everything saved there survives a restart)"""


def ask_model(messages: List[Dict[str, str]], max_tokens: int = 300) -> str:
    """One call to the local model through the HW1 adapter."""
    out = complete(messages, model=MODEL, temperature=0.0, max_tokens=max_tokens,
                   timeout=180, think=False)
    return out["content"].replace("<think>", "").replace("</think>", "").strip()


def consolidate_file() -> dict:
    """Consolidate MEMORY.md in place (a backup is kept as MEMORY.md.bak)."""
    shutil.copyfile(MEMORY_PATH, str(MEMORY_PATH) + ".bak")
    new_text, report = consolidate(load_memory_md())
    write_memory_md(new_text)
    return report


def show_memory() -> None:
    """/memory - print MEMORY.md and its status."""
    text = load_memory_md()
    due, reasons = needs_consolidation(text)
    print(text.rstrip())
    print(f"\n[memory] {count_memory_lines(text)} lines | last consolidated: "
          f"{read_last_consolidated(text)} | consolidation due: {due}"
          + (f" ({'; '.join(reasons)})" if reasons else ""))


def compact(history: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """/compact - consolidate MEMORY.md and summarize older conversation messages."""
    report = consolidate_file()
    print("[compact] MEMORY.md\n" + format_report(report))
    before = len(history)
    if before > KEEP_RECENT:
        old, recent = history[:-KEEP_RECENT], history[-KEEP_RECENT:]
        transcript = "\n".join(f"{m['role']}: {m['content']}" for m in old)
        summary = ask_model([{"role": "user", "content": "Summarize this conversation in 3 short "
                              "bullet points, keeping facts about the user:\n" + transcript + " /no_think"}])
        history = [{"role": "assistant", "content": "Summary of earlier conversation:\n" + summary}] + recent
    print(f"[compact] conversation messages: {before} -> {len(history)}")
    return history


def run_dream(history: List[Dict[str, str]]) -> None:
    """/dream - add durable facts from this conversation to MEMORY.md."""
    today = datetime.now(timezone.utc).date().isoformat()
    before = load_memory_md()
    new_text, added = dream(history, before, ask_model, today)
    write_memory_md(new_text)
    print(f"[dream] added {len(added)} fact(s); MEMORY.md lines: "
          f"{count_memory_lines(before)} -> {count_memory_lines(new_text)}")
    for fact in added:
        print("   " + fact.line())


def startup_check() -> None:
    """Consolidate MEMORY.md at start-up when the rules say it is due."""
    agent, memory = load_agent_md(), load_memory_md()
    print(f"[start] AGENT.md: {count_memory_lines(agent)} lines | MEMORY.md: "
          f"{count_memory_lines(memory)} lines | model: {MODEL}")
    due, reasons = needs_consolidation(memory)
    if due:
        print(f"[start] consolidation required: {'; '.join(reasons)}")
        report = consolidate_file()
        print(f"[start] consolidated: {report['lines_before']} -> {report['lines_after']} lines")
    else:
        print("[start] consolidation not required")


def main() -> None:
    """Interactive loop."""
    if not AGENT_PATH.exists() or not MEMORY_PATH.exists():
        raise SystemExit("AGENT.md and MEMORY.md must exist in the repository root.")
    startup_check()
    print("file-memory chat - type a message or /help")
    history: List[Dict[str, str]] = []
    while True:
        try:
            text = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text == "/exit":
            break
        if text in ("/help", "/memory", "/dream", "/compact"):
            if text == "/help":
                print(HELP)
            elif text == "/memory":
                show_memory()
            elif text == "/dream":
                run_dream(history)
            else:
                history = compact(history)
            continue
        history.append({"role": "user", "content": text})
        system = build_system_prompt(load_agent_md(), load_memory_md())
        reply = ask_model([{"role": "system", "content": system}] + history)
        history.append({"role": "assistant", "content": reply})
        print(f"assistant> {reply}")


if __name__ == "__main__":
    main()
