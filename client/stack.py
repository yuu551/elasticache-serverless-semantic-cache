import boto3

REGION = "ap-northeast-1"
STACK_NAME = "ServerlessSemanticCacheStack"


def outputs() -> dict[str, str]:
    """CDKのスタック出力（エンドポイントやRuntime ARN）を取得する"""
    cfn = boto3.client("cloudformation", region_name=REGION)
    stack = cfn.describe_stacks(StackName=STACK_NAME)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}
