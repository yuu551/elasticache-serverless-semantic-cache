import argparse
import asyncio
import json
import time

from glide import (
    Logger,
    LogLevel,
    GlideClusterClient,
    GlideClusterClientConfiguration,
    IamAuthConfig,
    NodeAddress,
    ServerCredentials,
    ServiceType,
)

from stack import REGION, outputs

INDEX_NAME = "semantic_cache_idx"
Logger.set_logger_config(LogLevel.ERROR)


async def connect() -> GlideClusterClient:
    out = outputs()
    config = GlideClusterClientConfiguration(
        addresses=[NodeAddress(out["CacheEndpoint"], 6379)],
        use_tls=True,
        request_timeout=5000,
        credentials=ServerCredentials(
            username="default.iam-user",
            iam_config=IamAuthConfig(
                cluster_name=out["CacheName"],
                service=ServiceType.ELASTICACHE,
                region=REGION,
            ),
        ),
    )
    return await GlideClusterClient.create(config)


def decode(value):
    """GLIDEが返すbytesを表示用に文字列へ変換する"""
    if isinstance(value, bytes):
        return value.decode()
    if isinstance(value, list):
        return [decode(v) for v in value]
    if isinstance(value, dict):
        return {decode(k): decode(v) for k, v in value.items()}
    return value


async def run(command: list[str]) -> None:
    client = await connect()
    start = time.perf_counter()
    result = await client.custom_command(command)
    elapsed = (time.perf_counter() - start) * 1000
    print(json.dumps(decode(result), ensure_ascii=False, indent=2))
    print(f"({elapsed:.1f} ms)")
    await client.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("info")
    text = sub.add_parser("text")
    text.add_argument("query")
    sub.add_parser("stats")
    sub.add_parser("ranking")
    args = parser.parse_args()

    if args.cmd == "info":
        # インデックスの一覧
        command = ["FT._LIST"]
    elif args.cmd == "text":
        # 全文検索でキャッシュ済みの質問文をキーワードで探す
        command = ["FT.SEARCH", INDEX_NAME, f"@query:{args.query}",
                   "RETURN", "3", "query", "tenant", "hits"]
    elif args.cmd == "stats":
        # テナントごとのキャッシュ件数とヒット回数の合計を集計する
        command = ["FT.AGGREGATE", INDEX_NAME, "@hits:[-inf +inf]",
                   "LOAD", "2", "@tenant", "@hits",
                   "GROUPBY", "1", "@tenant",
                   "REDUCE", "COUNT", "0", "AS", "entries",
                   "REDUCE", "SUM", "1", "@hits", "AS", "total_hits",
                   "SORTBY", "2", "@total_hits", "DESC"]
    else:
        # よくヒットしている質問の上位3件を集計する
        command = ["FT.AGGREGATE", INDEX_NAME, "@hits:[1 +inf]",
                   "LOAD", "3", "@query", "@tenant", "@hits",
                   "SORTBY", "2", "@hits", "DESC", "MAX", "3"]
    asyncio.run(run(command))


if __name__ == "__main__":
    main()
