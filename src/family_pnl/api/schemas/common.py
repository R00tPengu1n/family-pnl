"""Field types shared by several schemas."""

from datetime import date
from typing import Annotated

from pydantic import Field

from family_pnl.domain.ledger import EARLIEST_DATE, LATEST_DATE

# A date the service accepts: 2000-01-01 to 2099-12-31.
Day = Annotated[date, Field(ge=EARLIEST_DATE, le=LATEST_DATE)]
