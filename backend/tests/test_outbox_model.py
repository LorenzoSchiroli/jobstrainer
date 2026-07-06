import uuid
from backend.models import Outbox


async def test_outbox_row_can_be_inserted(db_session):
    event = Outbox(
        event_type="job_upserted",
        entity_id=uuid.uuid4(),
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)
    assert event.id is not None
    assert event.processed_at is None
