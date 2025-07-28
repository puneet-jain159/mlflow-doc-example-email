import os
import mlflow
from dotenv import load_dotenv

load_dotenv()

# Unity Catalog schema to store the prompt in
UC_CATALOG = os.environ.get('UC_CATALOG')
UC_SCHEMA = os.environ.get('UC_SCHEMA')

# Example prompt
prompt = """You are an expert sales communication assistant for CloudFlow Inc. Your task is to generate a personalized, professional follow-up email for our sales representatives to send to their customers at the end of the day.

## INPUT DATA
You will be provided with a JSON object containing:

{{my_data}}
... cut off ...
"""

mlflow.genai.register_prompt(
  name=f'{UC_CATALOG}.{UC_SCHEMA}.email_generation_demo',
  template=prompt,
  commit_message='Initial email generation template',
)