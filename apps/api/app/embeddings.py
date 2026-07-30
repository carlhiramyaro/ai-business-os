import os

from dotenv import load_dotenv

# Drop-in replacement for openai.OpenAI -- also instruments embeddings.create,
# not just chat completions. See docs/infra-guide.md.
from langfuse.openai import OpenAI

load_dotenv()

EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_DIMENSIONS = 1536  # text-embedding-3-small's native output size


def generate_embedding(text: str) -> list[float]:
    client = OpenAI()
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=text)
    return response.data[0].embedding
