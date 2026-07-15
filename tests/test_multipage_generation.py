from pds_core.routing_models import PDS2_SCHEMA, ModuleWorkRef, RouteLocator

from scoreform.templates import build_qr_payload


def test_multipage_qr_generation_uses_only_the_route_locator() -> None:
    locator = RouteLocator(
        PDS2_SCHEMA,
        ModuleWorkRef("scoreform", "class1", "quiz"),
        "rt_20000000000000000000000000000000",
    )
    payload = build_qr_payload(locator)
    assert payload == (
        "PDS2|m=scoreform|c=class1|w=quiz|"
        "r=rt_20000000000000000000000000000000"
    )
    assert "page" not in payload
    assert "student" not in payload
