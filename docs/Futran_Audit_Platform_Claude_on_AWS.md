---
title: Futran Audit Platform — Claude on AWS
tags: [futran, audit-platform, deployment, aws, ai]
updated: 2026-11-26
status: built and tested offline; not yet run against a live Claude Platform on AWS account
---

# Futran Audit Platform: Claude on AWS

The law library refresh, the AI court-case (litigation) refresh and Draft with AI can run on **Claude Platform on AWS**. The platform connects to it as its own AI provider, "Claude Platform on AWS", in Platform settings, or from environment variables.

## Why Claude Platform on AWS and not Amazon Bedrock

| | Claude Platform on AWS | Claude on Amazon Bedrock |
|---|---|---|
| Who runs it | Anthropic, reached through an AWS gateway | AWS |
| API | Anthropic's own Claude API (Messages API), same request format and model IDs (`claude-sonnet-5-5`, `claude-opus-5-5`) | Bedrock's API and Bedrock model IDs |
| Web search tool (`web_search_20250305`) | Available | Not available |
| Billing | AWS Marketplace, on the AWS bill | AWS bill |
| Sign-in | AWS IAM (SigV4) or an API key generated in the AWS Console | AWS IAM |

Refresh depends on Anthropic's web search tool: the first call of each geography searches the allowlisted sources, the second turns the research into checked JSON. Bedrock does not offer that tool, so a refresh cannot run there. Claude Platform on AWS has the first-party feature set, including tool use, structured outputs and prompt caching (AWS documentation, [Feature support](https://docs.aws.amazon.com/claude-platform/latest/userguide/feature-support.html), read 26 November 2026).

Two points from the same AWS page to weigh before using it for client work:

- Prompts and replies are processed by Anthropic outside AWS. Anthropic's commercial terms and data processing addendum apply, alongside the AWS Service Terms.
- It is a third-party offering, not covered by AWS compliance programmes (SOC, ISO, HIPAA eligibility). Use Anthropic's Trust Center for compliance evidence.

## One-time set-up in AWS

Source: AWS documentation, [Set up your account](https://docs.aws.amazon.com/claude-platform/latest/userguide/setup.html), [Authentication](https://docs.aws.amazon.com/claude-platform/latest/userguide/authentication.html) and [IAM actions](https://docs.aws.amazon.com/claude-platform/latest/userguide/iam-actions.html), read 26 November 2026.

1. **Subscribe.** In the AWS Console, open the **Claude Platform on AWS** service page and choose **Sign up**, then **Continue**. AWS handles the AWS Marketplace subscription; stay on the page for a few minutes until it redirects. Then enter the email address of the organisation's owner, follow the setup link sent to it, and complete the organisation details. This creates a new Anthropic organisation tied to the AWS account. It is separate from any existing Anthropic account Futran has: keys and workspaces do not carry over.
2. **Note the workspace ID and its region.** A default workspace is created at sign-up. Find its ID under **Workspaces** on the service page. It starts `wrkspc_`. Workspaces are bound to a region: the region you enter in the platform must be the workspace's region. Create a separate workspace if you want refresh costs kept apart.
3. **Choose how the platform signs its requests** (next section).

## API key or the server's AWS role

| | API key | Use the server's AWS role |
|---|---|---|
| What is stored in the platform | The key, encrypted like the other providers' keys. Only its last four characters are shown again | Nothing secret |
| Where it comes from | AWS Console, **Claude Platform on AWS › API keys › Generate a key**. Keys from the Claude Console (platform.claude.com) or Amazon Bedrock do not work | The ECS task role on Fargate (any credential in the AWS default credential chain works) |
| IAM permissions | The key's principal needs `aws-external-anthropic:CallWithBearerToken` and `aws-external-anthropic:CreateInference` on the workspace | The task role needs `aws-external-anthropic:CreateInference` on the workspace |
| Extra package on the server | None | `boto3` and `botocore`: included in the Docker image (`pip install -e ".[aws]"`) |
| Best for | The laptop, a pilot, any host outside AWS | Production on ECS Fargate: no long-lived key to rotate |

**The task role policy** (replace the region, account and workspace ID):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "aws-external-anthropic:CreateInference",
    "Resource": "arn:aws:aws-external-anthropic:us-east-1:123456789012:workspace/wrkspc_01AbCdEf23"
  }]
}
```

`CreateInference` authorises `POST /v1/messages`, the only route the platform calls. Web search runs inside that call. Add `aws-external-anthropic:CallWithBearerToken` to the policy of whoever holds an API key.

**boto3 for the AWS role.** The anthropic SDK signs with the server's AWS role through botocore. The Docker image installs it (`pip install -e ".[aws]"` in the Dockerfile), so the AWS role works out of the box on ECS. A laptop install does not include it; there, use an API key or install the `aws` extra. Without boto3, Test connection says: "Signing with the server's AWS role needs the boto3 package on the server".

## Network

Allow outbound HTTPS (TCP 443) from the task to `aws-external-anthropic.<region>.api.aws`, for example `aws-external-anthropic.us-east-1.api.aws`. Web search runs on Anthropic's side, so the task does not need to reach the searched sites. The NAT gateway or public IP the task already uses for email egress serves this (see [[Futran_Audit_Platform_Mail_Architecture]]); there is no separate outbound allowlist document, so this page and the deployment architecture page list the address. To check from a one-off task with the same network settings:

```
python -c "import socket; socket.create_connection(('aws-external-anthropic.us-east-1.api.aws',443),5); print('ok')"
```

## Settings in the platform

### Option A: Platform settings (recommended)

Sign in as the Futran Admin, open **Platform settings › AI provider**, and enter:

| Field | Value |
|---|---|
| Provider | Claude Platform on AWS |
| Model | `claude-sonnet-5-5` or `claude-opus-5-5` (the Claude model ID, not a Bedrock ID such as `anthropic.claude-…`) |
| AWS Region | the workspace's region, for example `us-east-1` |
| Workspace ID | `wrkspc_…` |
| Sign requests with | API key, or Use the server's AWS role |
| Gateway address | leave blank (the platform uses `https://aws-external-anthropic.<region>.api.aws`) |
| API key | only with API key |

Save, then press **Test connection**. It sends one small request. Failures are reported in plain words without repeating AWS's reply:

| Message starts | Usual cause |
|---|---|
| "could not be reached at aws-external-anthropic.…" | Wrong region, or the task cannot reach that address on port 443 |
| "refused the request (HTTP 403)" | Wrong workspace ID, workspace in another region, or the key or role lacks the IAM permission |
| "refused the credentials" | The API key is wrong or revoked |
| "does not recognise this request" | Wrong model name |
| "found no AWS credentials" | AWS role chosen but the task has no task role |
| "needs the boto3 package" | AWS role chosen but the image was built without `.[aws]` |

The saved connection is used by every AI feature, not only refresh. A saved connection always wins over the environment variables below.

### Option B: environment variables

With nothing saved in Platform settings, the platform uses Claude Platform on AWS when both of these are set (in Secrets Manager or the task definition):

| Variable | Value |
|---|---|
| `ANTHROPIC_AWS_REGION` | the workspace's region (required) |
| `ANTHROPIC_AWS_WORKSPACE_ID` | `wrkspc_…` (required) |
| `ANTHROPIC_AWS_API_KEY` | the API key; leave unset to sign with the task role |
| `ANTHROPIC_AWS_BASE_URL` | leave unset |
| `CLAUDE_MODEL` | `claude-sonnet-5-5` (the default) or another Claude model ID |

The order is: a saved connection, then `ANTHROPIC_API_KEY` (Anthropic's own API), then the `ANTHROPIC_AWS_*` settings. If `ANTHROPIC_API_KEY` is also set, it wins: remove it to switch to AWS. **Platform settings › AI provider** shows which one is in use now.

When a saved connection uses the server's AWS role, an `ANTHROPIC_AWS_API_KEY` in the environment is ignored for it.

## Checking that a refresh ran on AWS

1. **Platform settings › AI provider**: "In use now" reads "Claude Platform on AWS · claude-sonnet-5-5".
2. **Law library › Refresh and review**: refresh is switched on (no "Connect an AI provider" warning). Run one geography by hand.
3. The latest run shows the model that answered, the prompt version and the cost; open it for each geography's outcome and number of changes. A geography the provider could not check is listed in the run's warnings with the plain message from the table above. The screen does not name the provider; the run record does (`provider: anthropic_aws` for each geography in `GET /api/v1/admin/laws/refresh/<run id>`), as does the AI provider card.
4. In the AWS Console, usage appears under Claude Platform on AWS; IAM-signed calls appear in CloudTrail as `CreateInference` data events (if data events are logged).

## Open points

- Built and tested offline only (the SDK's own client with a simulated gateway). The first live run is untested: press Test connection, then run one geography before relying on it.
- Refresh costs use the `CLAUDE_*_USD_*` price settings, which are the direct API's list prices. Check the AWS Marketplace prices and adjust them if they differ.
