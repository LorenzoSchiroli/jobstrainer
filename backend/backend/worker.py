import asyncio
import logging

from backend.opensearch_client import init_opensearch
from backend.outbox.worker import reconcile_worker, retention_worker

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

logger = logging.getLogger(__name__)


async def main() -> None:
    await init_opensearch()
    await asyncio.gather(reconcile_worker(), retention_worker())


if __name__ == "__main__":
    asyncio.run(main())
