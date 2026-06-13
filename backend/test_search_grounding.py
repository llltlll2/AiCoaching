import os
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv("c:/Users/llltl/OneDrive/Documents/Projects/AiCoaching/backend/.env")
api_key = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=api_key)

try:
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents='What is the latest news on Python 3.14?',
        config=types.GenerateContentConfig(
            tools=[{"google_search": {}}],
            system_instruction="Output a JSON object with a single key 'news' containing a short summary of the latest news about Python 3.14. Output ONLY valid JSON, without any markdown formatting or backticks."
        )
    )
    print("Response JSON:")
    print(response.text)
except Exception as e:
    print(f"Error: {e}")
