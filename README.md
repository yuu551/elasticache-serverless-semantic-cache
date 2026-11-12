# elasticache-serverless-semantic-cache

Amazon ElastiCache Serverless for Valkey 9の検索（ベクトル・全文・タグ・数値・集計）と、Amazon Bedrock AgentCore Runtime V2で作るセマンティックキャッシュのサンプルです。

- ElastiCache Serverless for Valkey 9をパブリックエンドポイント（IAM認証・TLS 1.3）で作成します
- AgentCore Runtime V2（パブリックネットワーク）のエージェントが、テナントで絞り込んだベクトル検索でキャッシュを探します
- ローカルのPCからキャッシュへ直接接続し、全文検索と集計を実行できます

## 構成

| パス | 内容 |
| --- | --- |
| `bin/`, `lib/` | CDKアプリ（ElastiCache Serverless・AgentCore Runtime・IAM） |
| `agent/` | Strands Agents＋Valkey GLIDEのエージェント（Runtimeのコンテナ） |
| `client/` | Runtimeの呼び出しと、キャッシュへの全文検索・集計のスクリプト |

## 動作確認した環境

- リージョン: 東京（ap-northeast-1）
- Node.js 26.13.0 / pnpm / aws-cdk-lib 2.276.0 / AWS CDK CLI 2.1148.0
- Python 3.14 / uv
- Docker（Runtimeのイメージはarm64でビルドされます）

## デプロイ

```bash
pnpm install
pnpm cdk deploy
```

## 動かす

```bash
cd client
uv sync

# Runtimeを呼び出す（キャッシュミス → ヒット）
uv run invoke.py "VPNに接続する方法を教えて" --tenant acme
uv run invoke.py "VPNのつなぎ方を知りたい" --tenant acme

# 同じセッションで続けて呼び出す
SESSION=$(uuidgen)
uv run invoke.py "経費精算の締め日はいつ？" --tenant acme -s $SESSION

# ローカルのPCから全文検索と集計を実行する
uv run cache_ops.py text 'VPN*'
uv run cache_ops.py stats
uv run cache_ops.py ranking
```

## Janomeで日本語を分かち書きして全文検索する（任意）

`client/janome_search.py` は、検証用のインデックス（ja_idx）に質問文を5件登録し、原文と分かち書きしたフィールドで検索結果を比べるスクリプトです。セマンティックキャッシュのインデックスとは別なので、デプロイしたキャッシュでそのまま試せます。接続先は環境変数で指定します。

```bash
cd client
export VALKEY_HOST=<スタック出力のCacheEndpoint> VALKEY_CACHE_NAME=semantic-cache
uv run janome_search.py setup
uv run janome_search.py search 締め日
uv run janome_search.py cleanup
```

## 後片付け

```bash
pnpm cdk destroy
```
