from enum import StrEnum


class Currency(StrEnum):
    """Supported currencies (ISO 4217 codes)."""

    RUB = "RUB"
    BYN = "BYN"
    USD = "USD"

    @classmethod
    def parse(cls, code: str) -> "Currency":
        try:
            return cls(code.strip().upper())
        except ValueError:
            raise ValueError(f"unsupported currency: {code.strip()}") from None
