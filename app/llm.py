import os
import json
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

client = AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Simulated Tool
async def calculate_shipping(destination_country: str, weight_kg: float):
    # Mock logic
    base_rate = 10
    if destination_country.lower() == "us":
        return f"${base_rate + (weight_kg * 2)}"
    elif destination_country.lower() == "uk":
        return f"£{base_rate + (weight_kg * 1.5)}"
    else:
        return f"€{base_rate + (weight_kg * 3)}"

tools = [
    {
        "type": "function",
        "function": {
            "name": "calculate_shipping",
            "description": "Calculate shipping cost for a package.",
            "parameters": {
                "type": "object",
                "properties": {
                    "destination_country": {"type": "string", "description": "The country code (e.g. US, UK, FR)"},
                    "weight_kg": {"type": "number", "description": "Weight in kilograms"}
                },
                "required": ["destination_country", "weight_kg"]
            }
        }
    }
]

async def stream_chat_response(messages):
    """
    Streams the response from the LLM.
    Handles multi-step tool calling recursively.
    """
    current_messages = list(messages)
    
    # Allow up to 5 turns of tool calls to prevent infinite loops
    for _ in range(5):
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=current_messages,
            tools=tools,
            tool_choice="auto",
            stream=True
        )

        tool_calls = []
        content_accumulated = ""
        has_tool_call = False
        
        async for chunk in response:
            delta = chunk.choices[0].delta
            
            # Handle Tool Calls
            if delta.tool_calls:
                has_tool_call = True
                for tc in delta.tool_calls:
                    if len(tool_calls) <= tc.index:
                        tool_calls.append({"id": "", "function": {"name": "", "arguments": ""}})
                    
                    if tc.id:
                        tool_calls[tc.index]["id"] += tc.id
                    if tc.function.name:
                        tool_calls[tc.index]["function"]["name"] += tc.function.name
                    if tc.function.arguments:
                        tool_calls[tc.index]["function"]["arguments"] += tc.function.arguments
            
            # Handle Text Content
            if delta.content:
                content_accumulated += delta.content
                # Only stream content if we aren't building a tool call (usually mutually exclusive, but good for safety)
                if not has_tool_call: 
                     yield {"type": "token", "content": delta.content}

        # If no tool calls, we are done
        if not tool_calls:
            # If we had accumulated content that was streamed, we're good.
            break

        # If we have tool calls, process them and continue the loop
        assistant_msg = {
            "role": "assistant",
            "content": content_accumulated if content_accumulated else None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": tc["function"]
                } for tc in tool_calls
            ]
        }
        current_messages.append(assistant_msg)

        for tc in tool_calls:
            fn_name = tc["function"]["name"]
            fn_args_str = tc["function"]["arguments"]
            
            # Yield tool call event for frontend visualization
            yield {"type": "tool_call", "tool_name": fn_name, "tool_args": fn_args_str}
            
            try:
                fn_args = json.loads(fn_args_str)
            except json.JSONDecodeError:
                fn_args = {}
            
            result_str = ""
            if fn_name == "calculate_shipping":
                result = await calculate_shipping(**fn_args)
                result_str = str(result)
            else:
                 result_str = f"Error: Tool {fn_name} not found."

            # Yield tool result event
            yield {"type": "tool_result", "tool_name": fn_name, "result": result_str}
            
            current_messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": result_str
            })
        
        # Loop continues to next iteration to send tool outputs back to LLM


async def analyze_session(history):
    """
    Analyzes the conversation history and generates a summary.
    """
    transcript = ""
    for event in history:
        role = event.get('event_type', 'unknown')
        content = event.get('content', '')
        transcript += f"{role}: {content}\n"
    
    if not transcript.strip():
        return "No conversation history."

    prompt = f"Analyze the following conversation session and provide a concise summary of what happened, user intent, and outcome.\n\nTranscript:\n{transcript}"
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error generating summary: {e}"
