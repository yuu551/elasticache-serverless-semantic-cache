import * as path from 'node:path';
import * as cdk from 'aws-cdk-lib';
import * as agentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import { Platform } from 'aws-cdk-lib/aws-ecr-assets';
import * as elasticache from 'aws-cdk-lib/aws-elasticache';
import * as iam from 'aws-cdk-lib/aws-iam';
import type { Construct } from 'constructs';

const CACHE_NAME = 'semantic-cache';
const CACHE_USER = 'default.iam-user';

export class SemanticCacheStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ElastiCache Serverless for Valkey 9（パブリックエンドポイント）
    const cache = new elasticache.CfnServerlessCache(this, 'Cache', {
      serverlessCacheName: CACHE_NAME,
      engine: 'valkey',
      majorEngineVersion: '9',
      connectionType: 'public',
      userGroupId: 'default.iam-user-group',
    });

    // AgentCore Runtime V2（VPCなしのパブリックネットワーク）
    const runtime = new agentcore.Runtime(this, 'Runtime', {
      runtimeName: 'serverlessSemanticCache',
      agentRuntimeArtifact: agentcore.AgentRuntimeArtifact.fromAsset(
        path.join(import.meta.dirname, '../agent'),
        { platform: Platform.LINUX_ARM64 },
      ),
      platformVersion: agentcore.PlatformVersion.V2,
      networkConfiguration: agentcore.RuntimeNetworkConfiguration.usingPublicNetwork(),
      environmentVariables: {
        VALKEY_HOST: cache.attrEndpointAddress,
        VALKEY_CACHE_NAME: CACHE_NAME,
        VALKEY_USER: CACHE_USER,
      },
    });

    // IAM認証でキャッシュへ接続する権限（キャッシュとユーザーの両方が対象）
    runtime.addToRolePolicy(new iam.PolicyStatement({
      actions: ['elasticache:Connect'],
      resources: [
        cache.attrArn,
        this.formatArn({ service: 'elasticache', resource: 'user', resourceName: CACHE_USER, arnFormat: cdk.ArnFormat.COLON_RESOURCE_NAME }),
      ],
    }));

    // 埋め込みとLLMの呼び出し（jp推論プロファイルは東京・大阪のどちらかへ振り分けられる）
    runtime.addToRolePolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
      resources: [
        'arn:aws:bedrock:*::foundation-model/*',
        this.formatArn({ service: 'bedrock', resource: 'inference-profile', resourceName: '*' }),
      ],
    }));

    new cdk.CfnOutput(this, 'CacheEndpoint', { value: cache.attrEndpointAddress });
    new cdk.CfnOutput(this, 'CacheName', { value: CACHE_NAME });
    new cdk.CfnOutput(this, 'RuntimeArn', { value: runtime.agentRuntimeArn });
  }
}
