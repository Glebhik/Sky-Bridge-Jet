import importlib
import pkgutil


def import_domain_models(package_name: str = "sky_bridge_jet.modules") -> None:
    """Import every future bounded-context ``models`` module for Alembic metadata."""
    try:
        package = importlib.import_module(package_name)
    except ModuleNotFoundError as error:
        if error.name == package_name:
            return
        raise

    for module in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
        if module.name.endswith(".models"):
            importlib.import_module(module.name)
