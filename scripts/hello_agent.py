"""Smoke test: one Microsoft Agent Framework agent answering through Microsoft Foundry.

Usage:
    python scripts/hello_agent.py
"""

import asyncio
import os

from agent_framework import Agent
from agent_framework.openai import OpenAIChatCompletionClient
from dotenv import load_dotenv


def foundry_base_url(endpoint: str) -> str:
    """Normalize a Foundry endpoint to its OpenAI-compatible v1 base URL."""
    endpoint = endpoint.rstrip("/")
    if not endpoint.endswith("/openai/v1"):
        endpoint += "/openai/v1"
    return endpoint + "/"


async def main() -> None:
    """Create a tiny agent backed by a Foundry deployment and print its reply."""
    load_dotenv()
    endpoint = os.getenv("FOUNDRY_ENDPOINT", "")
    api_key = os.getenv("FOUNDRY_API_KEY", "")
    if not endpoint or "your-resource" in endpoint or not api_key or api_key == "your-key":
        raise SystemExit("FOUNDRY_ENDPOINT / FOUNDRY_API_KEY missing: copy .env.example to .env.")

    # The Foundry v1 endpoint is OpenAI-compatible; the model id is the deployment name.
    client = OpenAIChatCompletionClient(
        model=os.getenv("FOUNDRY_MODEL", "gpt-4.1-mini"),
        base_url=foundry_base_url(endpoint),
        api_key=api_key,
    )
    agent = Agent(
        client=client,
        name="HelloAnalyst",
        instructions="You are a concise football analyst. Answer in one sentence.",
    )
    result = await agent.run("Why does a goal in the 90th minute feel bigger than one in the 10th?")
    print(result.text)


if __name__ == "__main__":
    asyncio.run(main())
