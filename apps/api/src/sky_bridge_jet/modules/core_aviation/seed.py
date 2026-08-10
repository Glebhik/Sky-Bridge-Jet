from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid5

from sqlalchemy.orm import Session

from sky_bridge_jet.db.session import SessionLocal
from sky_bridge_jet.modules.core_aviation.models import Airport
from sky_bridge_jet.modules.core_aviation.repositories import AirportRepository

AIRPORT_NAMESPACE = UUID("84075be6-11aa-5f48-8c73-b97a459141f7")

AIRPORT_SEED_DATA: tuple[dict[str, object], ...] = (
    {
        "icao_code": "EIDW",
        "iata_code": "DUB",
        "name": "Dublin Airport",
        "city": "Dublin",
        "country_code": "IE",
        "latitude": Decimal("53.42130"),
        "longitude": Decimal("-6.27010"),
        "timezone": "Europe/Dublin",
    },
    {
        "icao_code": "EGLF",
        "iata_code": "FAB",
        "name": "Farnborough Airport",
        "city": "Farnborough",
        "country_code": "GB",
        "latitude": Decimal("51.27580"),
        "longitude": Decimal("-0.77630"),
        "timezone": "Europe/London",
    },
    {
        "icao_code": "LFPB",
        "iata_code": "LBG",
        "name": "Paris-Le Bourget Airport",
        "city": "Paris",
        "country_code": "FR",
        "latitude": Decimal("48.96940"),
        "longitude": Decimal("2.44140"),
        "timezone": "Europe/Paris",
    },
    {
        "icao_code": "LFMN",
        "iata_code": "NCE",
        "name": "Nice Cote d'Azur Airport",
        "city": "Nice",
        "country_code": "FR",
        "latitude": Decimal("43.65840"),
        "longitude": Decimal("7.21590"),
        "timezone": "Europe/Paris",
    },
    {
        "icao_code": "LSGG",
        "iata_code": "GVA",
        "name": "Geneva Airport",
        "city": "Geneva",
        "country_code": "CH",
        "latitude": Decimal("46.23810"),
        "longitude": Decimal("6.10890"),
        "timezone": "Europe/Zurich",
    },
    {
        "icao_code": "LSZH",
        "iata_code": "ZRH",
        "name": "Zurich Airport",
        "city": "Zurich",
        "country_code": "CH",
        "latitude": Decimal("47.46470"),
        "longitude": Decimal("8.54920"),
        "timezone": "Europe/Zurich",
    },
    {
        "icao_code": "LIML",
        "iata_code": "LIN",
        "name": "Milan Linate Airport",
        "city": "Milan",
        "country_code": "IT",
        "latitude": Decimal("45.44510"),
        "longitude": Decimal("9.27670"),
        "timezone": "Europe/Rome",
    },
    {
        "icao_code": "LEMD",
        "iata_code": "MAD",
        "name": "Adolfo Suarez Madrid-Barajas Airport",
        "city": "Madrid",
        "country_code": "ES",
        "latitude": Decimal("40.49830"),
        "longitude": Decimal("-3.56760"),
        "timezone": "Europe/Madrid",
    },
    {
        "icao_code": "LEBL",
        "iata_code": "BCN",
        "name": "Josep Tarradellas Barcelona-El Prat Airport",
        "city": "Barcelona",
        "country_code": "ES",
        "latitude": Decimal("41.29740"),
        "longitude": Decimal("2.08330"),
        "timezone": "Europe/Madrid",
    },
)


def seed_airports(session: Session) -> list[Airport]:
    """Idempotently load the intentionally small development/demo airport reference set."""
    repository = AirportRepository(session)
    seeded: list[Airport] = []

    def apply_seed() -> None:
        for airport_data in AIRPORT_SEED_DATA:
            icao_code = str(airport_data["icao_code"])
            airport = repository.get_by_icao(icao_code)
            if airport is None:
                airport = Airport(
                    id=uuid5(AIRPORT_NAMESPACE, icao_code),
                    **airport_data,
                )
                repository.add(airport)
            else:
                for field, value in airport_data.items():
                    setattr(airport, field, value)
                airport.is_active = True
            seeded.append(airport)
        session.flush()

    if session.in_transaction():
        apply_seed()
    else:
        with session.begin():
            apply_seed()
    return seeded


def main() -> None:
    with SessionLocal() as session:
        seed_airports(session)


if __name__ == "__main__":
    main()
