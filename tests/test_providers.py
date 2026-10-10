import json

import httpx
import pytest

from iris.config import Settings
from iris.providers import ProviderError, Providers
from iris.tools import ToolManager


def settings(**kwargs):
    return Settings(_env_file=None, **kwargs)


async def test_demo_makes_no_network_requests():
    def unexpected(request):
        pytest.fail("La demo no debe usar red")
    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
        provider = Providers(settings(iris_mode="demo"), client)
        assert (await provider.research("test"))["provider"] == "demo"
        assert (await provider.reason("test"))["provider"] == "demo"


async def test_gemini_grounding_and_auth():
    def handler(request):
        assert request.headers["x-goog-api-key"] == "test-key"
        assert "test-key" not in str(request.url)
        assert json.loads(request.content)["tools"] == [{"google_search": {}}]
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "internal", "thought": True}, {"text": "Respuesta"}]}, "groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://example.com", "title": "Fuente"}}]}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await Providers(settings(iris_mode="live", gemini_api_key="test-key"), client).research("test")
        assert result["text"] == "Respuesta"
        assert result["grounded"] and len(result["sources"]) == 1


async def test_xai_uses_search_and_extracts_sources():
    def handler(request):
        assert request.url.host == "api.x.ai"
        assert json.loads(request.content)["tools"] == [{"type": "web_search"}]
        return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": "Result", "annotations": [{"type": "url_citation", "url": "https://example.com", "title": "Example"}]}]}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await Providers(settings(iris_mode="live", iris_research_provider="xai", xai_api_key="fake"), client).research("test")
        assert result["provider"] == "xai" and result["grounded"]


async def test_gpt_never_receives_local_tool_credentials():
    def handler(request):
        payload = json.loads(request.content)
        assert request.url.path == "/v1/responses"
        assert payload["store"] is False and "tools" not in payload
        assert payload["input"] == "Solve"
        return httpx.Response(200, json={"output": [{"content": [{"type": "output_text", "text": "Answer"}]}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await Providers(settings(iris_mode="live", openai_api_key="fake"), client).reason("Solve")
        assert result["text"] == "Answer"


async def test_upstream_error_does_not_leak_body():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(401, text="sensitive-error-content"))) as client:
        with pytest.raises(ProviderError) as error:
            await Providers(settings(iris_mode="live", openai_api_key="fake"), client).reason("test")
        assert "401" in str(error.value) and "sensitive" not in str(error.value)


async def test_missing_key_does_not_silently_fake_success():
    async with httpx.AsyncClient() as client:
        with pytest.raises(ProviderError):
            await Providers(settings(iris_mode="live", openai_api_key=""), client).reason("test")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "https://user:pass@example.com", "https://example.com\\evil", "not-a-url"])
async def test_open_url_rejects_nonweb_or_credential_urls(url):
    async with httpx.AsyncClient() as client:
        manager = ToolManager(Providers(settings(), client))
        with pytest.raises(ValueError):
            manager.validate("open_url", {"url": url})


async def test_open_url_requires_approval_even_in_demo():
    async with httpx.AsyncClient() as client:
        manager = ToolManager(Providers(settings(), client))
        with pytest.raises(PermissionError):
            await manager.execute("open_url", {"url": "https://example.com"})
        result = await manager.execute("open_url", {"url": "https://example.com"}, approved=True)
        assert result == {"opened": False, "simulated": True, "url": "https://example.com"}


async def test_unknown_tools_and_extra_arguments_rejected():
    async with httpx.AsyncClient() as client:
        manager = ToolManager(Providers(settings(), client))
        with pytest.raises(ValueError):
            manager.validate("shell", {"command": "anything"})
        with pytest.raises(ValueError):
            manager.validate("device_status", {"approved": True})
