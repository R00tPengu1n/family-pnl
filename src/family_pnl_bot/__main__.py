"""`uv run python -m family_pnl_bot`: needs the bot token, the bot secret and the API URL."""

import asyncio

from family_pnl_bot.app import main

asyncio.run(main())
