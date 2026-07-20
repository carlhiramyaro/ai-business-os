import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()


def generate_chat_answer(question: str, context_chunks: list[str], history: list[dict]) -> str:
    """history: [{"role": "user"|"assistant", "content": "..."}], oldest first."""
    client = OpenAI()

    context_block = "\n\n".join(f"- {chunk}" for chunk in context_chunks) if context_chunks else "(no relevant context found)"
    system_prompt = (
        "You are a business analyst assistant answering questions about a specific "
        "small business, using only the context below (retrieved from that "
        "business's own report and data). If the context doesn't contain the "
        "answer, say so rather than guessing.\n\nContext:\n" + context_block
    )

    messages = [{"role": "system", "content": system_prompt}, *history, {"role": "user", "content": question}]

    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=messages,
    )
    return response.choices[0].message.content
