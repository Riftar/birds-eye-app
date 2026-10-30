import json

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
        developer_content = request.instructions
        if request.json_schema and binding.provider != ProviderId.META:
            # Baseten docs: Muse Spark Open does not support structured
            # outputs, so the schema is appended to the developer message
            # instead of using response_format.
            developer_content = (
                developer_content
                + "\n\nReturn only JSON matching this schema:\n"
                + json.dumps(request.json_schema)
            )
        body = {
            "model": binding.concrete_model,
            "messages": [
                {"role": "developer", "content": developer_content},
                {"role": "user", "content": request.prompt},
            ],
            "max_completion_tokens": request.max_tokens,
            "reasoning_effort": (
                self.settings.meta_reasoning_effort or self.settings.reasoning_effort
            )
            if binding.provider == ProviderId.META
            else self.settings.reasoning_effort,
        }
        if request.json_schema and binding.provider == ProviderId.META:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.json_schema_name or request.stage,
                    "schema": request.json_schema,
                    "strict": True,
                },
            }
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
            finish_reason = choice.get("finish_reason")
            if finish_reason == "length" and (
                not isinstance(content, str) or len(content.strip()) < 40
            ):
                error = ProviderError("EMPTY_CONTENT_LENGTH")
                error.usage = data.get("usage")
                error.finish_reason = finish_reason
                raise error
            if not isinstance(content, str) or not content.strip():
                raise ProviderError("MALFORMED_RESPONSE")
            usage = data.get("usage")
            if usage is not None and not isinstance(usage, dict):
                raise ProviderError("MALFORMED_RESPONSE")
            return ProviderReply(
                output=content,
                usage=usage,
                finish_reason=finish_reason,
                truncated=finish_reason == "length",
            )
        except (KeyError, IndexError, TypeError, ValueError):
            raise ProviderError("MALFORMED_RESPONSE") from None
