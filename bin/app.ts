import * as cdk from 'aws-cdk-lib';
import { SemanticCacheStack } from '../lib/semantic-cache-stack.ts';

const app = new cdk.App();
new SemanticCacheStack(app, 'ServerlessSemanticCacheStack', {
  env: { region: 'ap-northeast-1' },
});
