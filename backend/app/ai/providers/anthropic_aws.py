"""Claude Platform on AWS as a connected provider (26 Nov 2026): Anthropic's own Claude API, operated by Anthropic and
reached through an AWS gateway, `https://aws-external-anthropic.<region>.api.aws`, billed through AWS Marketplace.

Why not Claude on Amazon Bedrock: Bedrock does not offer the web search server tool (`web_search_20250305`) that law and
litigation refresh and Draft with AI depend on. Claude Platform on AWS has the first-party feature set, web search
included (docs.aws.amazon.com/claude-platform/latest/userguide/feature-support.html, checked 26 November 2026).

The calls are the Anthropic ones, unchanged: `AnthropicAIClient` (JSON), `AnthropicStructuredClient` (web search, then
JSON) and `AnthropicClaudeClient` (web search, free text). Only the SDK client differs: `anthropic.AnthropicAWS` (SDK 2.8
or later), wrapped in `Gateway`, which

- makes the SDK client on first use, so an old SDK or a missing boto3 shows up as a plain message on the call, not as
  a failure to load a page;
- passes the saved region, workspace ID and gateway address explicitly, so the SDK's own environment lookups
  (ANTHROPIC_AWS_WORKSPACE_ID, ANTHROPIC_AWS_BASE_URL, AWS_REGION) never override a saved connection;
- in "server's AWS role" mode, keeps SigV4 signing even when ANTHROPIC_AWS_API_KEY is set in the environment (the SDK
  would otherwise prefer that key);
- turns every SDK, HTTP and AWS signing failure into an `AIError` with a fixed message. The provider's response body is
  never repeated and the SDK error is not chained, so neither reaches a log.

Signing with the server's AWS role needs boto3 and botocore (`pip install "anthropic[aws]"`, the `aws` extra in
pyproject.toml). An API key needs nothing more than the anthropic package.
"""
import re

from app.ai.client import AIError, AnthropicAIClient

LABEL = "Claude Platform on AWS"
API_KEY, AWS_ROLE = "api_key", "aws_role"
AUTH_MODES = (API_KEY, AWS_ROLE)
GATEWAY = "https://aws-external-anthropic.{region}.api.aws"
# AWS region names: us-east-1, eu-central-2, ap-southeast-4, us-gov-west-1
REGION_RE = re.compile(r"^[a-z]{2}(-[a-z]+)+-\d{1,2}$")
# workspace IDs are "wrkspc_" and an alphanumeric identifier (docs.aws.amazon.com/claude-platform/latest/userguide/setup.html)
WORKSPACE_RE = re.compile(r"^wrkspc_[A-Za-z0-9_-]{1,100}$")
# exactly the regional gateway: aws-external-anthropic.<region>.api.aws (review 26 Nov: no S3 or other AWS-domain hosts, no port)
GATEWAY_HOST_RE = re.compile(r"^aws-external-anthropic\.[a-z]{2}(-[a-z]+)+-\d{1,2}(-fips)?\.api\.aws$")

NEEDS_SDK = "Claude Platform on AWS needs the anthropic package version 2.8 or later. Update it on the server (pip install -U anthropic)."
NEEDS_BOTO3 = ("Signing with the server's AWS role needs the boto3 package on the server (pip install \"anthropic[aws]\"). "
               "Install it, or use a Claude Platform on AWS API key instead.")
NO_CREDENTIALS = ("The server found no AWS credentials to sign with. On ECS, give the task a task role that may call Claude Platform on AWS; "
                  "or use a Claude Platform on AWS API key instead.")


def gateway_url(region: str) -> str:
    return GATEWAY.format(region=region)


def gateway_host_ok(host: str) -> bool:
    """A gateway host the API key may be sent to: the regional Claude Platform on AWS gateway and nothing else."""
    return bool(GATEWAY_HOST_RE.match((host or "").lower()))


def gateway_url_ok(url: str) -> bool:
    """An https address of the regional gateway on the default port (443 written out is allowed)."""
    from urllib.parse import urlparse

    try:
        p = urlparse((url or "").strip())
        port = p.port
    except ValueError:
        return False
    return p.scheme == "https" and port in (None, 443) and not p.username and not p.password and gateway_host_ok(p.hostname or "")


def sdk_class():
    """`anthropic.AnthropicAWS`, or a plain AIError when the installed SDK predates it. Tests replace this function."""
    try:
        from anthropic import AnthropicAWS
    except ImportError:
        raise AIError(NEEDS_SDK) from None
    return AnthropicAWS


def failure_message(e: BaseException, host: str) -> str:
    """A fixed message for one failure. Never the response body: it can name internal details."""
    import anthropic

    if isinstance(e, ModuleNotFoundError) and (e.name or "").split(".")[0] in ("boto3", "botocore"):
        return NEEDS_BOTO3
    if "credentials" in type(e).__name__.lower() or (isinstance(e, RuntimeError) and "aws credentials" in str(e).lower()):
        return NO_CREDENTIALS
    if isinstance(e, anthropic.APITimeoutError):
        return f"{LABEL} took too long to answer. Try again."
    if isinstance(e, anthropic.APIConnectionError):
        return (f"{LABEL} could not be reached at {host}. Check the region, and that the server can reach that address on port 443.")
    if isinstance(e, anthropic.APIStatusError):
        status = e.status_code
        if status == 401:
            return f"{LABEL} refused the credentials. Check the API key, or that the server's AWS role may call Claude Platform on AWS."
        if status == 403:
            return (f"{LABEL} refused the request (HTTP 403). Check the workspace ID, that the workspace is in this region, and that the API key "
                    "or the server's AWS role is allowed to use the workspace.")
        if status == 404:
            return f"{LABEL} does not recognise this request. Check the model name and the workspace ID."
        if status == 429:
            return f"{LABEL} reported too many requests or no remaining quota. Try again later or check the account's limits."
        if status >= 500:
            return f"{LABEL} is unavailable at the moment. Try again later."
        kind = ""
        body = getattr(e, "body", None)
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            t = str(body["error"].get("type") or "")
            kind = f", {t}" if re.fullmatch(r"[a-z_]{1,40}", t) else ""  # a fixed error code, never the message text
        return (f"{LABEL} rejected the request (HTTP {status}{kind}). Check the model name and the workspace ID, and that web search "
                "is turned on for the organisation in the Claude Platform on AWS console (the law and court-case refresh needs it).")
    if isinstance(e, anthropic.AnthropicError):
        return f"{LABEL} is not set up correctly on the server. Check the region and the workspace ID."
    return f"{LABEL} could not be reached ({type(e).__name__})."


class Gateway:
    """Stands where an `anthropic.Anthropic` client stands (`.messages.create(...)`), backed by `anthropic.AnthropicAWS`."""

    def __init__(self, *, auth_mode: str, api_key: str | None, region: str, workspace_id: str, base_url: str | None = None):
        self.auth_mode = auth_mode if auth_mode in AUTH_MODES else API_KEY
        self._api_key = api_key or None
        self.region = region
        self.workspace_id = workspace_id
        self.base_url = (base_url or "").rstrip("/") or gateway_url(region)
        self.http_client = None  # tests set an httpx2 client with a MockTransport before the first call
        self._sdk = None

    def __repr__(self) -> str:  # the key stays out of logs and tracebacks
        return f"Gateway(auth_mode={self.auth_mode!r}, region={self.region!r}, workspace_id={self.workspace_id!r}, base_url={self.base_url!r})"

    @property
    def host(self) -> str:
        return self.base_url.split("://", 1)[-1].split("/", 1)[0]

    @property
    def messages(self):
        return self

    def sdk(self):
        if self._sdk is None:
            kwargs: dict = {"aws_region": self.region, "workspace_id": self.workspace_id, "base_url": self.base_url}
            if self.auth_mode == API_KEY:
                kwargs = {"api_key": self._api_key} | kwargs
            if self.http_client is not None:
                kwargs["http_client"] = self.http_client
            client = sdk_class()(**kwargs)
            if self.auth_mode == AWS_ROLE and getattr(client, "_use_sigv4", True) is False:
                # the SDK chose ANTHROPIC_AWS_API_KEY from the environment; the saved choice is the server's AWS role
                client._use_sigv4 = True
                client.api_key = None
            self._sdk = client
        return self._sdk

    def create(self, **kwargs):
        try:
            return self.sdk().messages.create(**kwargs)
        except AIError:
            raise
        except Exception as e:  # noqa: BLE001 - every failure becomes one fixed message
            message = failure_message(e, self.host)
        raise AIError(message) from None


class AnthropicAWSProvider(AnthropicAIClient):
    provider = "anthropic_aws"
    label = LABEL

    def __init__(self, settings, *, model: str, region: str, workspace_id: str, auth_mode: str = API_KEY, api_key: str | None = None,
                 base_url: str | None = None):
        gateway = Gateway(auth_mode=auth_mode, api_key=api_key, region=region, workspace_id=workspace_id, base_url=base_url)
        super().__init__(settings, client=gateway, model=model)
        self.settings = settings

    def __repr__(self) -> str:
        return f"{type(self).__name__}(model={self.model!r}, client={self.client!r})"

    def refresh_client(self, settings):
        from app.refresh.claude import AnthropicStructuredClient

        return AnthropicStructuredClient(settings, client=self.client, model=self.model, provider=self.provider)

    def drafting_client(self, settings):
        from app.laws.refresh import AnthropicClaudeClient

        return AnthropicClaudeClient(settings, client=self.client, model=self.model, provider=self.provider)


def env_configured(settings) -> bool:
    return bool(getattr(settings, "anthropic_aws_region", None) and getattr(settings, "anthropic_aws_workspace_id", None))


def from_settings(settings, model: str | None = None) -> AnthropicAWSProvider | None:
    """The environment fallback (ANTHROPIC_AWS_REGION and ANTHROPIC_AWS_WORKSPACE_ID, optionally ANTHROPIC_AWS_API_KEY
    and ANTHROPIC_AWS_BASE_URL), or None when the region or the workspace ID is missing."""
    if not env_configured(settings):
        return None
    key = settings.anthropic_aws_api_key
    return AnthropicAWSProvider(settings, model=model or settings.claude_model, region=settings.anthropic_aws_region.strip().lower(),
                                workspace_id=settings.anthropic_aws_workspace_id.strip(), auth_mode=API_KEY if key else AWS_ROLE, api_key=key,
                                base_url=settings.anthropic_aws_base_url)
