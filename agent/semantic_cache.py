import json
import struct
import time
from hashlib import md5

import boto3
from glide import (
    GlideClusterClient,
    GlideClusterClientConfiguration,
    IamAuthConfig,
    NodeAddress,
    ServerCredentials,
    ServiceType,
)

INDEX_NAME = "semantic_cache_idx"
KEY_PREFIX = "cache:"


def _text(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)


class SemanticCache:
    def __init__(self, *, host: str, cache_name: str, user_id: str, region: str,
                 embedding_model_id: str, dims: int = 1024):
        self.embedding_model_id = embedding_model_id
        self.dims = dims
        self.bedrock = boto3.client("bedrock-runtime", region_name=region)

        # 接続設定だけを作っておく（IAMトークンの発行と接続はまだしない）
        self._config = GlideClusterClientConfiguration(
            addresses=[NodeAddress(host, 6379)],
            use_tls=True,
            request_timeout=5000,
            credentials=ServerCredentials(
                username=user_id,
                iam_config=IamAuthConfig(
                    cluster_name=cache_name,
                    service=ServiceType.ELASTICACHE,
                    region=region,
                ),
            ),
        )
        self._client: GlideClusterClient | None = None

    async def _get_client(self) -> GlideClusterClient:
        # Runtime V2はスナップショットから復元されるため、
        # 期限のあるIAMトークンを使う接続は最初のリクエストで作る
        if self._client is None:
            self._client = await GlideClusterClient.create(self._config)
            await self._setup_index(self._client)
        return self._client

    async def _setup_index(self, client: GlideClusterClient) -> None:
        indexes = [_text(i) for i in await client.custom_command(["FT._LIST"])]
        if INDEX_NAME in indexes:
            return
        await client.custom_command([
            "FT.CREATE", INDEX_NAME,
            "ON", "HASH",
            "PREFIX", "1", KEY_PREFIX,
            "SCHEMA",
            "query", "TEXT",
            "tenant", "TAG",
            "hits", "NUMERIC",
            "embedding", "VECTOR", "HNSW", "6",
            "TYPE", "FLOAT32",
            "DIM", str(self.dims),
            "DISTANCE_METRIC", "COSINE",
        ])

    def _embed(self, text: str) -> bytes:
        response = self.bedrock.invoke_model(
            modelId=self.embedding_model_id,
            body=json.dumps({"inputText": text}),
        )
        embedding = json.loads(response["body"].read())["embedding"]
        return struct.pack(f"{len(embedding)}f", *embedding)

    async def search(self, query: str, tenant: str, threshold: float) -> dict:
        connecting = self._client is None
        t_connect = time.perf_counter()
        client = await self._get_client()

        t0 = time.perf_counter()
        vec = self._embed(query)
        t1 = time.perf_counter()

        # ハイブリッド検索で同じテナントのキャッシュだけを対象にKNN検索する
        result = await client.custom_command([
            "FT.SEARCH", INDEX_NAME,
            f"@tenant:{{{tenant}}}=>[KNN 3 @embedding $vec AS score]",
            "PARAMS", "2", "vec", vec,
            "RETURN", "1", "score",
        ])
        t2 = time.perf_counter()
        timing = {
            "embedding": round((t1 - t0) * 1000, 1),
            "vector_search": round((t2 - t1) * 1000, 1),
        }
        if connecting:
            timing["connect_and_index"] = round((t0 - t_connect) * 1000, 1)

        if not result or result[0] == 0:
            return {"hit": False, "timing_ms": timing}

        # 結果は [件数, {キー: {フィールド: 値}}] の形で返る
        key, distance = min(
            ((k, float(_text(f[b"score"]))) for k, f in result[1].items()),
            key=lambda item: item[1],
        )
        similarity = 1 - distance / 2
        if similarity < threshold:
            return {"hit": False, "score": similarity, "timing_ms": timing}

        answer = await client.hget(key, "answer")
        await client.hincrby(key, "hits", 1)
        return {
            "hit": True,
            "answer": _text(answer),
            "score": similarity,
            "key": _text(key),
            "timing_ms": timing,
        }

    async def store(self, query: str, answer: str, tenant: str) -> None:
        client = await self._get_client()
        key = f"{KEY_PREFIX}{tenant}:{md5(query.encode()).hexdigest()}"
        await client.hset(key, {
            "query": query,
            "answer": answer,
            "tenant": tenant,
            "hits": "0",
            "embedding": self._embed(query),
        })
