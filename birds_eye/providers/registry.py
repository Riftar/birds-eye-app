from birds_eye.config import Settings
from birds_eye.providers.contracts import ModelBinding, ProviderId


def bindings(settings: Settings) -> list[ModelBinding]:
    return [
        ModelBinding(
            logical_model="muse-spark",
            provider=ProviderId.BASETEN,
            concrete_model="meta-models/muse-spark-open-1026",
            operation="text",
        ),
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
