from sky_bridge_jet.main import app

_ERROR_REF = {"$ref": "#/components/schemas/ErrorResponse"}

_PAYMENT_ROUTES = {
    ("/api/v1/bookings/{booking_id}/payment", "post"): True,
    ("/api/v1/bookings/{booking_id}/payment", "get"): False,
    ("/api/v1/payments/{payment_id}", "get"): False,
    ("/api/v1/payments/{payment_id}/authorize", "post"): True,
    ("/api/v1/payments/{payment_id}/capture", "post"): True,
    ("/api/v1/payments/{payment_id}/void", "post"): True,
    ("/api/v1/payments/{payment_id}/refunds", "post"): True,
    ("/api/v1/payments/{payment_id}/refunds", "get"): False,
    ("/api/v1/payments/{payment_id}/allocation", "get"): False,
}


def test_payment_routes_document_safe_error_envelope() -> None:
    schema = app.openapi()
    for (path, method), documents_conflict in _PAYMENT_ROUTES.items():
        responses = schema["paths"][path][method]["responses"]
        assert responses["422"]["content"]["application/json"]["schema"] == _ERROR_REF
        assert responses["500"]["content"]["application/json"]["schema"] == _ERROR_REF
        assert responses["404"]["content"]["application/json"]["schema"] == _ERROR_REF
        if documents_conflict:
            assert responses["409"]["content"]["application/json"]["schema"] == _ERROR_REF


def test_openapi_does_not_leak_default_validation_schema() -> None:
    schema = app.openapi()
    assert "HTTPValidationError" not in schema["components"]["schemas"]


def test_payment_status_enum() -> None:
    schema = app.openapi()
    payment = schema["components"]["schemas"]["PaymentResponse"]
    status_ref = payment["properties"]["status"]["$ref"].rsplit("/", 1)[-1]
    assert set(schema["components"]["schemas"][status_ref]["enum"]) == {
        "CREATED",
        "AUTHORIZED",
        "AUTHORIZATION_FAILED",
        "CAPTURED",
        "CAPTURE_FAILED",
        "CANCELLED",
        "PARTIALLY_REFUNDED",
        "REFUNDED",
    }


def test_openapi_has_no_card_credential_fields() -> None:
    # No request/response schema should ever expose raw payment credentials.
    schema = app.openapi()
    forbidden = ("pan", "cvv", "cvc", "card_number", "cardnumber", "track", "pin")
    for name, component in schema["components"]["schemas"].items():
        for field in component.get("properties", {}):
            assert field.lower() not in forbidden, f"{name}.{field}"
