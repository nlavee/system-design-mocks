from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import Book

class Observer(ABC):
    @abstractmethod
    def update(self, book: Book) -> None:
        pass

class Subject(ABC):
    @abstractmethod
    def add_observer(self, observer: Observer) -> None:
        pass

    @abstractmethod
    def remove_observer(self, observer: Observer) -> None:
        pass

    @abstractmethod
    def notify_observers(self) -> None:
        pass
