from birds_eye.providers.contracts import (
    ModelBinding,
    ModelRequest,
    ProviderError,
    ProviderReply,
)


class DisabledTransport:
    async def invoke(
        self, binding: ModelBinding, request: ModelRequest
    ) -> ProviderReply:
        raise ProviderError(
            "INTEGRATION_NOT_READY", "Live provider integration is disabled."
        )


class LiveTransport:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client

    async def invoke(
        self, binding: ModelBinding, request: ModelRequest
    ) -> ProviderReply:
        import httpx

        from birds_eye.providers.contracts import ProviderId

        configs = {
            ProviderId.BASETEN: (
                self.settings.baseten_base_url,
                self.settings.baseten_api_key,
            ),
            ProviderId.META: (
                self.settings.meta_model_api_base_url,
                self.settings.model_api_key,
            ),
            ProviderId.MODAL: (
                self.settings.modal_muse_endpoint,
                self.settings.modal_token_secret,
            ),
        }
        url, key = configs[binding.provider]
        if not url or not key:
            raise ProviderError("CONFIGURATION_ERROR")
        body = {
            "model": binding.concrete_model,
            "messages": [{"role": "user", "content": request.prompt}],
            "max_tokens": request.max_tokens,
        }
        if binding.provider == ProviderId.META and self.settings.meta_reasoning_effort:
            body["reasoning_effort"] = self.settings.meta_reasoning_effort
        try:
            if self.client is not None:
                response = await self.client.post(
                    url.rstrip("/") + "/chat/completions",
                    headers={"Authorization": "Bearer " + key.get_secret_value()},
                    json=body,
                )
            else:
                async with httpx.AsyncClient(
                    timeout=self.settings.provider_timeout_seconds
                ) as client:
                    response = await client.post(
                        url.rstrip("/") + "/chat/completions",
                        headers={"Authorization": "Bearer " + key.get_secret_value()},
                        json=body,
                    )
        except httpx.TimeoutException:
            raise ProviderError("TIMEOUT") from None
        except httpx.RequestError:
            raise ProviderError("CONNECTION_ERROR") from None
        status = response.status_code
        if status >= 400:
            code = (
                "AUTHENTICATION_ERROR"
                if status in (401, 403)
                else "RATE_LIMITED"
                if status == 429
                else "PROVIDER_5XX"
                if status >= 500
                else "INVALID_REQUEST"
            )
            raise ProviderError(code)
        try:
            data = response.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
            if not content and choice.get("finish_reason") == "length":
                raise ProviderError("EMPTY_CONTENT_LENGTH")
            if not isinstance(content, str) or not content.strip():
                raise ProviderError("MALFORMED_RESPONSE")
            usage = data.get("usage")
            if usage is not None and not isinstance(usage, dict):
                raise ProviderError("MALFORMED_RESPONSE")
            return ProviderReply(output=content, usage=usage)
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError("MALFORMED_RESPONSE") from None
