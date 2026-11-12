"""Janomeで分かち書きした質問文をValkeyの全文検索で探す"""
import argparse
import asyncio
import json
import os
import time

from glide import (
    GlideClusterClient,
    GlideClusterClientConfiguration,
    IamAuthConfig,
    Logger,
    LogLevel,
    NodeAddress,
    ServerCredentials,
    ServiceType,
)
from janome.tokenizer import Tokenizer

REGION = "ap-northeast-1"
INDEX_NAME = "ja_idx"
KEY_PREFIX = "ja:"
# 検索に使う品詞（助詞・助動詞・記号は捨てる）
CONTENT_POS = ("名詞", "動詞", "形容詞")
QUESTIONS = [
    "VPNに接続する方法を教えて",
    "VPNのつなぎ方を知りたい",
    "経費精算の締め日はいつ？",
    "経費の精算はいつまでに出せばいい？",
    "有給休暇の申請方法は？",
]

Logger.set_logger_config(LogLevel.ERROR)
tokenizer = Tokenizer()


def tokenize(text: str) -> list[str]:
    """内容語の基本形を取り出す（「つなぎ」→「つなぐ」のように活用をそろえる）"""
    return [t.base_form for t in tokenizer.tokenize(text)
            if t.part_of_speech.split(",")[0] in CONTENT_POS]


async def connect() -> GlideClusterClient:
    config = GlideClusterClientConfiguration(
        addresses=[NodeAddress(os.environ["VALKEY_HOST"], 6379)],
        use_tls=True,
        request_timeout=5000,
        credentials=ServerCredentials(
            username="default.iam-user",
            iam_config=IamAuthConfig(
                cluster_name=os.environ["VALKEY_CACHE_NAME"],
                service=ServiceType.ELASTICACHE,
                region=REGION,
            ),
        ),
    )
    return await GlideClusterClient.create(config)


def decode(value):
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, list):
        return [decode(v) for v in value]
    if isinstance(value, dict):
        return {decode(k): decode(v) for k, v in value.items()}
    return value


async def setup(client: GlideClusterClient) -> None:
    indexes = [decode(i) for i in await client.custom_command(["FT._LIST"])]
    if INDEX_NAME in indexes:
        await client.custom_command(["FT.DROPINDEX", INDEX_NAME])
    # 原文（query）と分かち書きした語（tokens）の両方を全文検索の対象にする
    await client.custom_command([
        "FT.CREATE", INDEX_NAME, "ON", "HASH", "PREFIX", "1", KEY_PREFIX,
        "SCHEMA", "query", "TEXT", "tokens", "TEXT", "NOSTEM",
    ])
    for i, q in enumerate(QUESTIONS):
        tokens = " ".join(tokenize(q))
        await client.hset(f"{KEY_PREFIX}{i}", {"query": q, "tokens": tokens})
        print(f"{q} -> {tokens}")


async def search(client: GlideClusterClient, field: str, words: list[str]) -> None:
    # 語ごとに条件を並べるとAND検索になる（例: @tokens:経費 @tokens:精算）
    query = " ".join(f"@{field}:{w}" for w in words)
    start = time.perf_counter()
    result = await client.custom_command(
        ["FT.SEARCH", INDEX_NAME, query, "RETURN", "1", "query"])
    elapsed = (time.perf_counter() - start) * 1000
    result = decode(result)
    hits = [v["query"] for v in result[1].values()] if result[0] else []
    print(f"{query} -> {result[0]}件 {json.dumps(hits, ensure_ascii=False)} ({elapsed:.1f} ms)")


async def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    s = sub.add_parser("search")
    s.add_argument("keywords")
    sub.add_parser("cleanup")
    args = parser.parse_args()

    client = await connect()
    if args.cmd == "setup":
        await setup(client)
    elif args.cmd == "search":
        # 原文のフィールドはそのまま、分かち書きのフィールドは検索語も同じように分割する
        await search(client, "query", [f"{args.keywords}*"])
        await search(client, "tokens", tokenize(args.keywords))
    else:
        await client.custom_command(["FT.DROPINDEX", INDEX_NAME])
        for i in range(len(QUESTIONS)):
            await client.delete([f"{KEY_PREFIX}{i}"])
    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
