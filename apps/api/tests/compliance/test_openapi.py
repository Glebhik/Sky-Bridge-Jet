from sky_bridge_jet.main import app

_ERROR_REF = {"$ref": "#/components/schemas/ErrorResponse"}

_COMPLIANCE_ROUTES = {
    ("/api/v1/operators/{operator_id}/admission", "post"): True,
    ("/api/v1/operators/{operator_id}/admission", "get"): False,
    ("/api/v1/operators/{operator_id}/admission/submit", "post"): True,
    ("/api/v1/operators/{operator_id}/admission/review", "post"): True,
    ("/api/v1/operators/{operator_id}/evidence", "post"): True,
    ("/api/v1/operators/{operator_id}/evidence", "get"): False,
    ("/api/v1/evidence/{evidence_id}", "get"): False,
    ("/api/v1/evidence/{evidence_id}/review", "post"): True,
    ("/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization", "post"): True,
    ("/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/authorization/review", "post"): True,
    ("/api/v1/operators/{operator_id}/eligibility", "get"): False,
    ("/api/v1/operators/{operator_id}/aircraft/{aircraft_id}/eligibility", "get"): False,
}


def test_compliance_routes_document_safe_error_envelope() -> None:
    schema = app.openapi()
    for (path, method), documents_conflict in _COMPLIANCE_ROUTES.items():
        responses = schema["paths"][path][method]["responses"]
        assert responses["422"]["content"]["application/json"]["schema"] == _ERROR_REF
        assert responses["500"]["content"]["application/json"]["schema"] == _ERROR_REF
        assert responses["404"]["content"]["application/json"]["schema"] == _ERROR_REF
        if documents_conflict:
            assert responses["409"]["content"]["application/json"]["schema"] == _ERROR_REF


def test_openapi_does_not_leak_default_validation_schema() -> None:
    schema = app.openapi()
    assert "HTTPValidationError" not in schema["components"]["schemas"]


def test_offer_and_confirm_document_compliance_conflict() -> None:
    schema = app.openapi()
    # The gate is surfaced on the existing commercial routes as a 409.
    assert (
        schema["paths"]["/api/v1/offers"]["post"]["responses"]["409"]["content"][
            "application/json"
        ]["schema"]
        == _ERROR_REF
    )
    confirm = "/api/v1/bookings/{booking_id}/confirm"
    assert (
        schema["paths"][confirm]["post"]["responses"]["409"]["content"]["application/json"][
            "schema"
        ]
        == _ERROR_REF
    )


def test_no_personal_identity_or_document_content_fields() -> None:
    # Compliance evidence must reference metadata/storage, never store raw content
    # or personal identity documents.
    schema = app.openapi()
    forbidden = ("passport", "national_id", "document_content", "file_bytes", "beneficial_owner")
    for component in schema["components"]["schemas"].values():
        for field in component.get("properties", {}):
            assert field.lower() not in forbidden
