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


def test_operator_history_and_detail_openapi_are_bounded_and_safe() -> None:
    schema = app.openapi()
    history = schema["paths"]["/api/v1/me/operator-bookings/history"]["get"]
    detail = schema["paths"]["/api/v1/me/operator-bookings/{booking_id}"]["get"]
    parameters = {item["name"]: item for item in history["parameters"]}
    assert parameters["limit"]["schema"] == {
        "type": "integer",
        "maximum": 100,
        "minimum": 1,
        "default": 20,
        "title": "Limit",
    }
    assert parameters["offset"]["schema"]["minimum"] == 0
    assert parameters["offset"]["schema"]["default"] == 0
    assert parameters["status"]["required"] is False
    assert detail["parameters"][0]["name"] == "booking_id"
    assert detail["parameters"][0]["schema"]["format"] == "uuid"

    safe = schema["components"]["schemas"]["OperatorBookingReadView"]["properties"]
    assert {
        "operator_amount_minor",
        "currency",
        "legs",
        "aircraft_registration",
        "confirmed_at",
        "rejected_at",
        "cancelled_at",
    } <= safe.keys()
    assert {
        "customer_id",
        "platform_fee_minor",
        "tax_amount_minor",
        "total_amount_minor",
        "payment",
        "provider_status",
        "rejection_note",
    }.isdisjoint(safe)
