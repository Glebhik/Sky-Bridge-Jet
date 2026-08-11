from sky_bridge_jet.main import app

_ERROR_REF = {"$ref": "#/components/schemas/ErrorResponse"}

# Booking routes and whether they document a 409 conflict. Every route documents
# 404, and the app documents 422 and 500 globally.
_BOOKING_ROUTES = {
    ("/api/v1/bookings", "post"): True,
    ("/api/v1/bookings/{booking_id}", "get"): False,
    ("/api/v1/trip-requests/{trip_request_id}/booking", "get"): False,
    ("/api/v1/bookings/{booking_id}/confirm", "post"): True,
    ("/api/v1/bookings/{booking_id}/reject", "post"): True,
    ("/api/v1/bookings/{booking_id}/cancel", "post"): True,
}


def test_booking_routes_document_safe_error_envelope() -> None:
    schema = app.openapi()
    for (path, method), documents_conflict in _BOOKING_ROUTES.items():
        responses = schema["paths"][path][method]["responses"]
        assert responses["422"]["content"]["application/json"]["schema"] == _ERROR_REF
        assert responses["500"]["content"]["application/json"]["schema"] == _ERROR_REF
        assert responses["404"]["content"]["application/json"]["schema"] == _ERROR_REF
        if documents_conflict:
            assert responses["409"]["content"]["application/json"]["schema"] == _ERROR_REF


def test_openapi_does_not_leak_default_validation_schema() -> None:
    schema = app.openapi()
    assert "HTTPValidationError" not in schema["components"]["schemas"]


def test_booking_response_status_enum() -> None:
    schema = app.openapi()
    booking = schema["components"]["schemas"]["BookingResponse"]
    status_ref = booking["properties"]["status"]["$ref"].rsplit("/", 1)[-1]
    assert set(schema["components"]["schemas"][status_ref]["enum"]) == {
        "PENDING_OPERATOR_CONFIRMATION",
        "CONFIRMED",
        "REJECTED",
        "CANCELLED",
    }
