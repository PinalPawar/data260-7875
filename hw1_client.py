
import json
import sys
from pathlib import Path

# Make src/ importable regardless of where this script is run from.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from model_client import complete  # noqa: E402

AGENT_MD_PATH = Path(__file__).resolve().parent / "AGENT.md"


def load_system_prompt() -> str:
    if AGENT_MD_PATH.exists():
        return AGENT_MD_PATH.read_text().strip()
    return "You are a helpful assistant."


def print_stats(history, turn_count, cumulative_input, cumulative_output):
    # json.dumps() only reads history, it never mutates it.
    history_json = json.dumps(history)
    print(
        f"[stats] turns={turn_count} "
        f"cumulative_input_tokens={cumulative_input} "
        f"cumulative_output_tokens={cumulative_output} "
        f"cumulative_total_tokens={cumulative_input + cumulative_output} "
        f"history_length_chars={len(history_json)}"
    )


def main():
    history = [{"role": "system", "content": load_system_prompt()}]

    turn_count = 0
    cumulative_input = 0
    cumulative_output = 0

    print("hw1_client -- type a message, or /stats, or /exit")

    while True:
        try:
            user_input = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not user_input:
            continue
        if user_input == "/exit":
            break
        if user_input == "/stats":
            print_stats(history, turn_count, cumulative_input, cumulative_output)
            continue

        history.append({"role": "user", "content": user_input})
        result = complete(history)
        history.append({"role": "assistant", "content": result["content"]})

        turn_count += 1
        cumulative_input += result["input_tokens"]
        cumulative_output += result["output_tokens"]

        print(f"assistant> {result['content']}")
        print(
            f"[turn {turn_count}] input_tokens={result['input_tokens']} "
            f"output_tokens={result['output_tokens']} "
            f"total_tokens={result['total_tokens']}"
        )

    print(
        f"\n[exit] total_turns={turn_count} "
        f"cumulative_input_tokens={cumulative_input} "
        f"cumulative_output_tokens={cumulative_output} "
        f"cumulative_total_tokens={cumulative_input + cumulative_output}"
    )


if __name__ == "__main__":
    main()