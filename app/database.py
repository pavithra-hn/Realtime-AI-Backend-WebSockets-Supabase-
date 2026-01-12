import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("Warning: SUPABASE_URL or SUPABASE_KEY not not found in environment variables.")

supabase: Client = None

try:
    if url and key and not key.startswith("sb_publishable"):
        supabase = create_client(url, key)
    else:
        print("Invalid or missing Supabase credentials. Using MOCK database.")
except Exception as e:
    print(f"Failed to initialize Supabase: {e}. Using MOCK database.")

import asyncio

async def create_session(user_id: str, session_id: str = None):
    if not supabase:
        print(f"[MOCK DB] execute: insert session {session_id} for {user_id}")
        return {"session_id": session_id, "user_id": user_id}
        
    data = {"user_id": user_id}
    if session_id:
        data["session_id"] = session_id
        
    try:
        response = await asyncio.to_thread(lambda: supabase.table("sessions").insert(data).execute())
        return response.data[0]
    except Exception as e:
        print(f"[DB ERROR] Failed to create session (using mock fallback): {e}")
        return {"session_id": session_id, "user_id": user_id}

async def log_event(session_id: str, event_type: str, content: str, metadata: dict = None):
    if not supabase:
        print(f"[MOCK DB] execute: insert event {event_type} for session {session_id}")
        return

    data = {
        "session_id": session_id,
        "event_type": event_type,
        "content": content,
        "metadata": metadata or {}
    }
    try:
        await asyncio.to_thread(lambda: supabase.table("session_events").insert(data).execute())
    except Exception as e:
        print(f"[DB ERROR] Failed to log event (ignoring): {e}")

async def update_session_summary(session_id: str, summary: str, end_time: str):
    if not supabase:
        print(f"[MOCK DB] execute: update session {session_id} with summary")
        return

    try:
        await asyncio.to_thread(lambda: supabase.table("sessions").update({
            "summary": summary,
            "end_time": end_time
        }).eq("session_id", session_id).execute())
    except Exception as e:
        print(f"[DB ERROR] Failed to update session (ignoring): {e}")

async def get_session_history_for_summary(session_id: str):
    if not supabase:
        print(f"[MOCK DB] execute: fetch history for {session_id}")
        return []

    try:
        response = await asyncio.to_thread(lambda: supabase.table("session_events").select("event_type, content").eq("session_id", session_id).order("created_at").execute())
        return response.data
    except Exception as e:
        print(f"[DB ERROR] Failed to fetch history (ignoring): {e}")
        return []
