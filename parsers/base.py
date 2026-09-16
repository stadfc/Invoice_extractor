from abc import ABC, abstractmethod

class InvoiceParserStrategy(ABC):
    """Abstrakcyjna klasa bazowa (interfejs) dla każdego dostawcy faktur."""

    @property
    @abstractmethod
    def keywords(self) -> list[str]:
        """Lista unikalnych słów kluczowych występujących w tekście PDF tego dostawcy."""
        pass

    @property
    @abstractmethod
    def vendor_name(self) -> str:
        """Przyjazna dla użytkownika nazwa dostawcy wyświetlana w komunikatach."""
        pass

    currency = "EUR"

    @abstractmethod
    def parse(self, page_text_list: list[str]) -> tuple[list[list], float]:
        """
        Logika specyficzna dla dostawcy.
        Zwraca: (macierz_produktów, kwota_calkowita_faktury)
        """
        pass