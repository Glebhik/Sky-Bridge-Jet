from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from sky_bridge_jet.db.base import Base
from sky_bridge_jet.db.session import get_db
from sky_bridge_jet.main import app
from sky_bridge_jet.modules.core_aviation.seed import seed_airports


def test_customer_endpoint_normalizes_email_and_returns_safe_validation_errors() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            created = client.post(
                "/api/v1/customers",
                json={
                    "customer_type": "INDIVIDUAL",
                    "display_name": "Aisling Byrne",
                    "primary_email": "AISLING@example.test",
                    "preferred_currency": "EUR",
                    "timezone": "Europe/Dublin",
                },
            )
            invalid = client.post(
                "/api/v1/customers",
                json={
                    "customer_type": "INDIVIDUAL",
                    "display_name": "Aisling Byrne",
                    "primary_email": "not-an-email",
                    "preferred_currency": "EUR",
                    "timezone": "Europe/Dublin",
                },
            )
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)

    assert created.status_code == 201
    assert created.json()["primary_email"] == "aisling@example.test"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert "input" not in str(invalid.json())


def test_customer_endpoint_rejects_blank_identity_fields() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/customers",
                json={
                    "customer_type": "INDIVIDUAL",
                    "display_name": "   ",
                    "primary_email": "aisling@example.test",
                    "preferred_currency": "EUR",
                    "timezone": "Europe/Dublin",
                },
            )
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_trip_endpoints_enforce_state_transition_rules() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory.begin() as session:
        seed_airports(session)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            customer = client.post(
                "/api/v1/customers",
                json={
                    "customer_type": "INDIVIDUAL",
                    "display_name": "Aisling Byrne",
                    "primary_email": "aisling@example.test",
                    "preferred_currency": "EUR",
                    "timezone": "Europe/Dublin",
                },
            ).json()
            airports = client.get("/api/v1/airports").json()
            trip = client.post(
                "/api/v1/trip-requests",
                json={
                    "customer_id": customer["id"],
                    "legs": [
                        {
                            "origin_airport_id": airports[0]["id"],
                            "destination_airport_id": airports[1]["id"],
                            "departure_at": "2026-09-01T14:00:00+00:00",
                            "passenger_count": 1,
                        }
                    ],
                },
            ).json()
            submitted = client.post(
                f"/api/v1/trip-requests/{trip['id']}/submit",
                json={"expected_version": trip["version"]},
            )
            invalid = client.post(
                f"/api/v1/trip-requests/{trip['id']}/submit",
                json={"expected_version": submitted.json()["version"]},
            )
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)

    assert submitted.status_code == 200
    assert submitted.json()["status"] == "SUBMITTED"
    assert invalid.status_code == 409
    assert invalid.json()["error"]["code"] == "invalid_state_transition"


def test_operator_and_aircraft_endpoints_persist_relationships() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            operator = client.post(
                "/api/v1/operators",
                json={
                    "legal_name": "Example Aviation Limited",
                    "country_code": "IE",
                    "contact_email": "ops@example.test",
                },
            ).json()
            aircraft = client.post(
                "/api/v1/aircraft",
                json={
                    "operator_id": operator["id"],
                    "manufacturer": "Cessna",
                    "model": "Citation CJ3+",
                    "category": "VERY_LIGHT_JET",
                    "registration": "ei-abc",
                    "passenger_capacity": 7,
                },
            )
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)

    assert aircraft.status_code == 201
    assert aircraft.json()["operator_id"] == operator["id"]
    assert aircraft.json()["registration"] == "EI-ABC"


def test_operator_endpoint_rejects_blank_trading_name() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/operators",
                json={
                    "legal_name": "Example Aviation Limited",
                    "trading_name": "   ",
                    "country_code": "IE",
                    "contact_email": "ops@example.test",
                },
            )
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_trip_endpoint_rejects_passengers_owned_by_another_customer() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        seed_airports(session)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            first_customer = client.post(
                "/api/v1/customers",
                json={
                    "customer_type": "INDIVIDUAL",
                    "display_name": "First Customer",
                    "primary_email": "first@example.test",
                    "preferred_currency": "EUR",
                    "timezone": "Europe/Dublin",
                },
            ).json()
            second_customer = client.post(
                "/api/v1/customers",
                json={
                    "customer_type": "INDIVIDUAL",
                    "display_name": "Second Customer",
                    "primary_email": "second@example.test",
                    "preferred_currency": "EUR",
                    "timezone": "Europe/Dublin",
                },
            ).json()
            passenger = client.post(
                "/api/v1/passengers",
                json={
                    "customer_id": second_customer["id"],
                    "first_name": "Guest",
                    "last_name": "Passenger",
                },
            ).json()
            airports = client.get("/api/v1/airports").json()
            response = client.post(
                "/api/v1/trip-requests",
                json={
                    "customer_id": first_customer["id"],
                    "passenger_ids": [passenger["id"]],
                    "legs": [
                        {
                            "origin_airport_id": airports[0]["id"],
                            "destination_airport_id": airports[1]["id"],
                            "departure_at": "2026-09-01T14:00:00+00:00",
                            "passenger_count": 1,
                        }
                    ],
                },
            )
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(engine)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "domain_validation_error"
