import uuid as _uuid
import json
import logging
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from langgraph.types import Command

from backend.database import get_session
from backend.models import User, Job, Company
from backend.tailorer.models import ApplicantProfile, Application
from backend.tailorer.schemas import ProfileUpsert, ProfileResponse
from backend.tailorer.state import TailorerState
from backend.tailorer.agent import build_graph
from backend.auth.dependencies import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tailorer", tags=["tailorer"])


# ── Profile endpoints (unchanged) ────────────────────────────────────────────

@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = ApplicantProfile(user_id=current_user.id)
        session.add(profile)
        await session.commit()
        await session.refresh(profile)
    return ProfileResponse.from_profile(profile)


@router.put("/profile", response_model=ProfileResponse)
async def upsert_profile(
    body: ProfileUpsert,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == current_user.id)
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = ApplicantProfile(user_id=current_user.id)
        session.add(profile)
    for field, val in body.model_dump(exclude_unset=True).items():
        setattr(profile, field, val)
    await session.commit()
    await session.refresh(profile)
    return ProfileResponse.from_profile(profile)


# ── Auth helper ───────────────────────────────────────────────────────────────

async def _get_user_from_token(token: str, session: AsyncSession) -> User:
    from backend.auth.jwt import decode_access_token
    user_id = decode_access_token(token)
    if not user_id:
        raise ValueError("Invalid token")
    result = await session.execute(select(User).where(User.id == _uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")
    return user


# ── Interrupt handler ─────────────────────────────────────────────────────────

async def _handle_apply_fills(ws: WebSocket, val: dict, thread_id: str = "", token: str = "") -> dict:
    await ws.send_json({
        "type": "apply_fills",
        "commands": val.get("commands", []),
        "thread_id": thread_id,
        "token": token,
    })
    return await ws.receive_json()


async def _handle_interrupt(ws: WebSocket, interrupt_val: dict, thread_id: str = "", token: str = "") -> dict:
    if interrupt_val.get("type") == "apply_fills":
        return await _handle_apply_fills(ws, interrupt_val, thread_id=thread_id, token=token)
    logger.warning("[tailorer] unknown interrupt type: %s", interrupt_val.get("type"))
    return {"type": "unknown"}


# ── WebSocket session ─────────────────────────────────────────────────────────

@router.websocket("/ws/{job_id}")
async def tailorer_ws(
    websocket: WebSocket,
    job_id: _uuid.UUID,
    token: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    await websocket.accept()
    try:
        user = await _get_user_from_token(token, session)
    except Exception:
        await websocket.close(code=4001)
        return

    job_result = await session.execute(select(Job).where(Job.id == job_id))
    job = job_result.scalar_one_or_none()
    if not job:
        await websocket.send_json({"type": "error", "message": "Job not found"})
        await websocket.close()
        return

    profile_result = await session.execute(
        select(ApplicantProfile).where(ApplicantProfile.user_id == user.id)
    )
    profile = profile_result.scalar_one_or_none()
    if not profile or not profile.cv_text:
        await websocket.send_json({"type": "error", "message": "No CV on file. Upload your CV first."})
        await websocket.close()
        return

    thread_id = str(_uuid.uuid4())
    await websocket.send_json({"type": "session_started", "thread_id": thread_id})

    config = {"configurable": {"thread_id": thread_id}}

    from backend.main import get_checkpointer
    checkpointer = get_checkpointer()
    graph = build_graph(checkpointer)

    base_state: TailorerState = {
        "job_id": str(job.id),
        "user_id": str(user.id),
        "job_title": job.title,
        "job_description": job.description or "",
        "profile": {
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "email": profile.email,
            "phone": profile.phone,
            "city": profile.city,
            "country": profile.country,
            "work_auth": profile.work_auth,
            "urls": profile.urls or {},
            "extra_qa": profile.extra_qa or {},
        },
        "cv_text": profile.cv_text or "",
        "cv_bytes": b"",
        "cl_bytes": b"",
        "cl_text": "",
        "last_snapshot": None,
        "fill_commands": [],
        "last_feedback": None,
        "retry_count": 0,
        "status": "mapping",
    }

    is_first_pass = True

    try:
        while True:  # outer: keep WS alive across fill passes
            msg = await websocket.receive_json()
            msg_type = msg.get("type", "")

            if msg_type == "new_session":
                logger.info("[tailorer] new_session requested — closing WS")
                break

            if msg_type == "submitted":
                logger.info("[tailorer] submit detected — writing Application row")
                try:
                    app_record = Application(user_id=user.id, job_id=job_id)
                    session.add(app_record)
                    await session.commit()
                    await websocket.send_json({"type": "application_recorded"})
                except Exception:
                    await session.rollback()
                    logger.warning("[tailorer] Application row already exists or write failed")
                continue

            if msg_type != "start_or_fill":
                logger.warning("[tailorer] unexpected message type=%s — ignored", msg_type)
                continue

            snapshot = msg.get("snapshot")
            feedback_text = msg.get("text", "")

            if is_first_pass:
                current_input: Any = {
                    **base_state,
                    "last_snapshot": snapshot,
                    "last_feedback": feedback_text or None,
                }
                is_first_pass = False
            else:
                current_input = {
                    "last_snapshot": snapshot,
                    "last_feedback": feedback_text or None,
                    "retry_count": 0,
                    "status": "mapping",
                    "fill_commands": [],
                }

            # inner: drive map → apply (with interrupt loop) to END
            while True:
                await graph.ainvoke(current_input, config)
                state_snap = await graph.aget_state(config)

                if not state_snap.next:
                    values = state_snap.values or {}
                    final_status = values.get("status")
                    fill_commands = values.get("fill_commands", [])
                    uncertain = [str(c["index"]) for c in fill_commands if c.get("uncertain")]

                    if final_status == "filled":
                        await websocket.send_json({
                            "type": "filled",
                            "filled_count": len(fill_commands),
                            "uncertain_fields": uncertain,
                        })
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Fill pass failed (status: {final_status})",
                        })
                    break  # back to outer loop — wait for next start_or_fill

                interrupts = [i for task in state_snap.tasks for i in task.interrupts]
                if not interrupts:
                    logger.warning("[tailorer] graph not done but no interrupts — breaking")
                    break

                logger.info("[tailorer] interrupt: %s", interrupts[0].value.get("type"))
                resume_val = await _handle_interrupt(
                    websocket, interrupts[0].value, thread_id=thread_id, token=token
                )
                current_input = Command(resume=resume_val)

    except WebSocketDisconnect:
        logger.info("[tailorer] WebSocket disconnected")
    except Exception as e:
        logger.exception("[tailorer] unhandled exception: %s", e)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


# ── File download endpoint (unchanged) ───────────────────────────────────────

@router.get("/files/{thread_id}/{file_type}")
async def download_tailored_file(
    thread_id: str,
    file_type: str,
    token: str = Query(...),
    session: AsyncSession = Depends(get_session),
):
    from fastapi.responses import Response
    try:
        user = await _get_user_from_token(token, session)
    except Exception:
        raise HTTPException(status_code=403, detail="Invalid token")

    if file_type not in ("cv", "cover_letter"):
        raise HTTPException(status_code=400, detail="file_type must be 'cv' or 'cover_letter'")

    from backend.main import get_checkpointer
    checkpointer = get_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}
    graph = build_graph(checkpointer)
    state_snapshot = await graph.aget_state(config)
    if not state_snapshot or not state_snapshot.values:
        raise HTTPException(status_code=404, detail="Session not found")

    values = state_snapshot.values
    if values.get("user_id") != str(user.id):
        raise HTTPException(status_code=403, detail="Forbidden")

    key = "cv_bytes" if file_type == "cv" else "cl_bytes"
    file_bytes = values.get(key, b"")
    if not file_bytes:
        raise HTTPException(status_code=404, detail="File not yet generated")

    filename = "tailored_cv.docx" if file_type == "cv" else "cover_letter.docx"
    return Response(
        content=file_bytes,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
