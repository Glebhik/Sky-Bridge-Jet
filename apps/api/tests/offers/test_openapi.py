from sky_bridge_jet.main import app

_ERROR_REF = {"$ref": "#/components/schemas/ErrorResponse"}

# Offer routes and the conflict (409) responses they must document. Every offer
# route additionally documents 404, and the app documents 422 and 500 globally.
_OFFER_ROUTES = {
    ("/api/v1/offers", "post"): True,
    ("/api/v1/offers/{offer_id}", "get"): False,
    ("/api/v1/offers/{offer_id}", "patch"): True,
    ("/api/v1/offers/{offer_id}/submit", "post"): True,
    ("/api/v1/offers/{offer_id}/withdraw", "post"): True,
    ("/api/v1/trip-requests/{trip_request_id}/offers", "get"): False,
    ("/api/v1/trip-requests/{trip_request_id}/offers/{offer_id}/select", "post"): True,
}


def test_offer_routes_document_safe_error_envelope() -> None:
    schema = app.openapi()
    for (path, method), documents_conflict in _OFFER_ROUTES.items():
        operation = schema["paths"][path][method]
        responses = operation["responses"]
        # Safe envelope for validation, persistence failure, and not-found.
        assert responses["422"]["content"]["application/json"]["schema"] == _ERROR_REF
        assert responses["500"]["content"]["application/json"]["schema"] == _ERROR_REF
        assert responses["404"]["content"]["application/json"]["schema"] == _ERROR_REF
        if documents_conflict:
            assert responses["409"]["content"]["application/json"]["schema"] == _ERROR_REF


def test_openapi_does_not_leak_default_validation_schema() -> None:
    schema = app.openapi()
    assert "HTTPValidationError" not in schema["components"]["schemas"]
    assert "ValidationError" not in schema["components"]["schemas"]


def test_offer_response_exposes_effective_status_enum() -> None:
    schema = app.openapi()
    offer_schema = schema["components"]["schemas"]["OperatorOfferResponse"]
    status_ref = offer_schema["properties"]["status"]["$ref"]
    enum_name = status_ref.rsplit("/", 1)[-1]
    assert set(schema["components"]["schemas"][enum_name]["enum"]) == {
        "DRAFT",
        "SUBMITTED",
        "WITHDRAWN",
        "EXPIRED",
        "SELECTED",
    }
