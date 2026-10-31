from birds_eye.providers.contracts import ProviderId
from birds_eye.providers.registry import bindings


def test_model_bindings_and_capabilities(configured_settings):
    models = bindings(configured_settings)
    muse = [m for m in models if m.logical_model == "muse-spark"]
    assert [(m.provider, m.concrete_model, m.operation) for m in muse] == [
        (ProviderId.BASETEN, "meta-models/muse-spark-open-1026", "text"),
        (ProviderId.MODAL, "mock-modal-muse-deployment", "text"),
        (ProviderId.META, "muse-spark-1.3-contributor", "text"),
    ]
    sam = [m for m in models if m.logical_model == "sam-3.1"]
    assert [(m.provider, m.concrete_model, m.operation) for m in sam] == [
        (ProviderId.META, "sam-3.1", "segmentation")
    ]


def test_unconfigured_modal_has_no_binding(settings):
    assert all(m.provider != ProviderId.MODAL for m in bindings(settings))
