import os
import time

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

from semantic_cache import SemanticCache

REGION = os.environ["AWS_REGION"]
LLM_MODEL_ID = os.getenv("LLM_MODEL_ID", "jp.anthropic.claude-haiku-5-5")
THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0.8"))

# 設定とBedrockクライアントは起動時（スナップショット前）に作ってよい
cache = SemanticCache(
    host=os.environ["VALKEY_HOST"],
    cache_name=os.environ["VALKEY_CACHE_NAME"],
    user_id=os.getenv("VALKEY_USER", "default.iam-user"),
    region=REGION,
    embedding_model_id=os.getenv("EMBEDDING_MODEL_ID", "amazon.titan-embed-text-v2:0"),
)
model = BedrockModel(model_id=LLM_MODEL_ID, region_name=REGION)

app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload: dict) -> dict:
    prompt = payload["prompt"]
    tenant = payload.get("tenant", "default")
    start = time.perf_counter()

    cached = await cache.search(prompt, tenant, THRESHOLD)
    if cached["hit"]:
        return {
            "response": cached["answer"],
            "cache_hit": True,
            "similarity_score": round(cached["score"], 4),
            "cache_key": cached["key"],
            "timing_ms": {
                **cached["timing_ms"],
                "total": round((time.perf_counter() - start) * 1000, 1),
            },
        }

    # キャッシュミスのときだけLLMで回答を作り、キャッシュに保存する
    agent_start = time.perf_counter()
    agent = Agent(
        model=model,
        system_prompt="社内ヘルプデスクとして、日本語で300文字程度で簡潔に回答してください。",
        callback_handler=None,
    )
    result = await agent.invoke_async(prompt)
    answer = str(result).strip()
    agent_ms = (time.perf_counter() - agent_start) * 1000

    await cache.store(prompt, answer, tenant)
    return {
        "response": answer,
        "cache_hit": False,
        "model_id": LLM_MODEL_ID,
        "timing_ms": {
            **cached["timing_ms"],
            "agent_invocation": round(agent_ms, 1),
            "total": round((time.perf_counter() - start) * 1000, 1),
        },
    }


if __name__ == "__main__":
    app.run()
