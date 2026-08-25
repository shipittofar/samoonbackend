from abc import ABC, abstractmethod
from seeders.registry import SeedRegistry


class BaseSeeder(ABC):
    """
    Every seeder must implement `run`, receiving the shared registry
    so it can both register its own objects and consume others'.
    """

    label: str = "base"

    @abstractmethod
    def run(self, registry: SeedRegistry, stdout) -> None:
        ...