import asyncio
import json
import logging
from datetime import datetime, timezone
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from app.database import create_session, log_event, update_session_summary, get_session_history_for_summary
from app.llm import stream_chat_response, analyze_session

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Realtime AI Backend")

# Mount client directory for static assets if needed, though we just serve index.html
app.mount("/client", StaticFiles(directory="client"), name="client")

@app.get("/")
async def root():
    return FileResponse("client/index.html")

async def process_session_end(session_id: str):
    logger.info(f"Processing session end for {session_id}")
    try:
        # Retrieve history
        history = await get_session_history_for_summary(session_id)
        if not history:
            logger.warning(f"No history found for {session_id}")
            return

        # Generate summary
        summary = await analyze_session(history)
        
        # Update session
        end_time = datetime.now(timezone.utc).isoformat()
        await update_session_summary(session_id, summary, end_time)
        logger.info(f"Session {session_id} summarized and closed.")
        
    except Exception as e:
        logger.error(f"Error processing session end: {e}")

@app.websocket("/ws/session/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    
    user_id = websocket.query_params.get("user_id", "anonymous")
    
    # Conversation History (State Management)
    messages = [
        {"role": "system", "content": """You are a helpful AI assistant. You can calculate shipping costs using the available tool.

RESPONSE GUIDELINES:
- Be concise and direct. Answer the question without unnecessary filler.
- DO NOT end every response with phrases like "If you have any other questions, feel free to ask!" or "How can I assist you further?" - only use these occasionally when appropriate (e.g., at session start or after completing a complex task).
- When explaining complex topics, use a structured format with clear headings and bullet points.
- Match the user's tone - if they're casual, be conversational; if formal, be professional.
- For simple questions (math, facts), give brief answers without elaborate explanations unless asked."""}
    ]
    
    # Initialize session in DB
    try: 
        await create_session(user_id, session_id)
    except Exception as e:
        logger.warning(f"Session insert failed (maybe exists): {e}")

    try:
        while True:
            data = await websocket.receive_text()
            
            # 1. Log User Message
            await log_event(session_id, "user_message", data)
            
            messages.append({"role": "user", "content": data})
            
            # 2. Stream AI Response
            ai_response_content = ""
            
            async for event in stream_chat_response(messages):
                event_type = event.get("type")
                
                if event_type == "token":
                    content = event["content"]
                    # Send JSON structure for token to ensure explicit streaming protocol
                    await websocket.send_json({"type": "content", "value": content})
                    ai_response_content += content
                    
                elif event_type == "tool_call":
                    tool_name = event["tool_name"]
                    tool_args = event["tool_args"]
                    # Notify client of tool usage
                    await websocket.send_json({"type": "tool_start", "tool": tool_name, "args": tool_args})
                    await log_event(session_id, "tool_call", tool_name, metadata={"args": tool_args})
                    
                elif event_type == "tool_result":
                    tool_name = event["tool_name"]
                    result = event["result"]
                    # Notify client of tool result
                    await websocket.send_json({"type": "tool_end", "tool": tool_name, "result": result})
                    await log_event(session_id, "tool_result", result, metadata={"tool_name": tool_name})

            # 3. Log AI Response
            await log_event(session_id, "ai_message", ai_response_content)
            
            messages.append({"role": "assistant", "content": ai_response_content})

    except WebSocketDisconnect:
        logger.info(f"Client disconnected: {session_id}")
        # 4. Post-Session Processing
        asyncio.create_task(process_session_end(session_id))
    except Exception as e:
        logger.error(f"Error: {e}")
        try:
            await websocket.close()
        except:
            pass
