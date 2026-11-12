import argparse
import json
import time
import uuid

import boto3

from stack import REGION, outputs


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--tenant", "-t", default="default")
    parser.add_argument("--session-id", "-s", default=None)
    args = parser.parse_args()

    runtime_arn = outputs()["RuntimeArn"]
    client = boto3.client("bedrock-agentcore", region_name=REGION)
    start = time.perf_counter()
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        runtimeSessionId=args.session_id or str(uuid.uuid4()),
        payload=json.dumps({"prompt": args.prompt, "tenant": args.tenant}).encode(),
    )
    result = json.loads(b"".join(response["response"]))
    elapsed = (time.perf_counter() - start) * 1000
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"呼び出し全体: {elapsed:.1f} ms")


if __name__ == "__main__":
    main()
