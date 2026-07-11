from unittest.mock import patch, AsyncMock

from backend import worker


async def test_worker_main_inits_opensearch_then_runs_both_loops():
    with patch("backend.worker.init_opensearch", new_callable=AsyncMock) as mock_init, \
         patch("backend.worker.reconcile_worker", new_callable=AsyncMock) as mock_reconcile, \
         patch("backend.worker.retention_worker", new_callable=AsyncMock) as mock_retention:
        await worker.main()

    mock_init.assert_awaited_once()
    mock_reconcile.assert_awaited_once()
    mock_retention.assert_awaited_once()
