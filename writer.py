"""HW8 Part 2: the Writer agent as its own process. All its input and output goes through Kafka.

    python writer.py

Part 3 switches (env): IDEMPOTENCY=0|1  COMMIT_MODE=after|before  MAX_RETRIES=N  WORK_DELAY_S=S
HW8_FAKE_LLM=1 uses the offline stand-in instead of Ollama. See kafka_hw8/agent_base.py.
"""

from kafka_hw8.agents import Writer, main

if __name__ == "__main__":
    main(Writer)
