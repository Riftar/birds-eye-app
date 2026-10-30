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
