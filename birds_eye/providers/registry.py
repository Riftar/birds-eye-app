from birds_eye.config import Settings
from birds_eye.providers.contracts import ModelBinding, ProviderId


def bindings(settings: Settings) -> list[ModelBinding]:
    result = [
        ModelBinding(
            logical_model="muse-spark",
            provider=ProviderId.BASETEN,
            concrete_model="meta-models/muse-spark-open-1026",
            operation="text",
        )
    ]
    if settings.modal_muse_model_id and (
        settings.provider_mode == "stub" or settings.modal_muse_endpoint
    ):
        result.append(
            ModelBinding(
                logical_model="muse-spark",
                provider=ProviderId.MODAL,
                concrete_model=settings.modal_muse_model_id,
                operation="text",
            )
        )
    result.extend(
        [
            ModelBinding(
                logical_model="muse-spark",
                provider=ProviderId.META,
                concrete_model=settings.meta_muse_model,
                operation="text",
            ),
            ModelBinding(
                logical_model="sam-3.1",
                provider=ProviderId.META,
                concrete_model="sam-3.1",
                operation="segmentation",
            ),
        ]
    )
    return result
