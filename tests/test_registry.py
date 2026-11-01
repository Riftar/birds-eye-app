from birds_eye.config import Settings
from birds_eye.providers.contracts import ProviderId
from birds_eye.providers.registry import bindings


def test_registry_muse_bindings_are_baseten_then_meta_only(configured_settings):
    models = bindings(configured_settings)
    muse = [m for m in models if m.logical_model == "muse-spark"]
    assert [(m.provider, m.concrete_model, m.operation) for m in muse] == [
        (ProviderId.BASETEN, "meta-models/muse-spark-open-1026", "text"),
        (ProviderId.META, "muse-spark-1.3-contributor", "text"),
    ]
    sam = [m for m in models if m.logical_model == "sam-3.1"]
    assert [(m.provider, m.concrete_model, m.operation) for m in sam] == [
        (ProviderId.META, "sam-3.1", "segmentation")
    ]


def test_no_modal_settings_required(settings):
    assert (
        not {
            "modal_muse_endpoint",
            "modal_muse_model_id",
            "modal_budget_cap_usd",
        }
        & Settings.model_fields.keys()
    )
    muse = [m for m in bindings(settings) if m.logical_model == "muse-spark"]
    assert [m.provider for m in muse] == [ProviderId.BASETEN, ProviderId.META]
