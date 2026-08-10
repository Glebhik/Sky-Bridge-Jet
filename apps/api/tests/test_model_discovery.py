import sys
from pathlib import Path

from sky_bridge_jet.db.base import Base
from sky_bridge_jet.db.model_discovery import import_domain_models


def test_model_discovery_imports_future_bounded_context_models(tmp_path: Path, monkeypatch) -> None:
    package_root = tmp_path / "model_discovery_fixture"
    models_file = package_root / "modules" / "foundation" / "models.py"
    models_file.parent.mkdir(parents=True)

    for package in (
        package_root / "__init__.py",
        package_root / "modules" / "__init__.py",
        package_root / "modules" / "foundation" / "__init__.py",
    ):
        package.write_text("")

    models_file.write_text(
        "\n".join(
            (
                "from sqlalchemy.orm import Mapped, mapped_column",
                "",
                "from sky_bridge_jet.db.base import Base",
                "",
                "class DiscoveryFixture(Base):",
                '    __tablename__ = "model_discovery_fixture"',
                "    id: Mapped[int] = mapped_column(primary_key=True)",
                "",
            )
        )
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    try:
        import_domain_models("model_discovery_fixture.modules")
        assert "model_discovery_fixture" in Base.metadata.tables
    finally:
        Base.metadata.remove(Base.metadata.tables["model_discovery_fixture"])
        for module_name in tuple(sys.modules):
            if module_name.startswith("model_discovery_fixture"):
                del sys.modules[module_name]
