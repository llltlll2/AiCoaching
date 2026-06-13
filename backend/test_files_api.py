import os
from dotenv import load_dotenv
from google import genai

load_dotenv("c:/Users/llltl/OneDrive/Documents/Projects/AiCoaching/backend/.env")
api_key = os.environ.get("GEMINI_API_KEY")

client = genai.Client(api_key=api_key)

print("Listing files:")
for f in client.files.list():
    print(f.name, getattr(f, 'display_name', 'no_display_name'), getattr(f, 'state', 'no_state'))
