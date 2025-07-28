import json
import os
import mlflow
from databricks.sdk import WorkspaceClient
import asyncio
import subprocess

mlflow.openai.autolog()


# Initialize OpenAI client
w = WorkspaceClient()  # Auto-configures from environment or ~/.databrickscfg
openai_client = w.serving_endpoints.get_open_ai_client()

# Get model name from environment variable with a default fallback
LLM_MODEL = os.getenv("LLM_MODEL")
if not LLM_MODEL:
    raise ValueError("LLM_MODEL environment variable is not set")

# Unity Catalog schema to store the prompt in
UC_CATALOG = os.environ.get('UC_CATALOG')
UC_SCHEMA = os.environ.get('UC_SCHEMA')



# No global prompt - will be loaded each time


def _validate_openai_client():
    """Validate that OpenAI client is available"""
    if not openai_client:
        raise RuntimeError("OpenAI client not available")



def load_email_prompt():
    """
    Load the email generation prompt from Unity Catalog registry.
    This function is traced by MLflow for monitoring and debugging.
    """
    # Set an alias for the prompt version
    try:
        # Use the prompt in your application
        prompt_uri = f"prompts:/{UC_CATALOG}.{UC_SCHEMA}.email_generation_demo/2"
        
        # Load prompt from registry
        loaded_prompt = mlflow.genai.load_prompt(prompt_uri)
        
        
        return loaded_prompt.template , loaded_prompt.version
        
    except Exception as e:
        # Log error metrics
        print(f"Warning: Could not load prompt from registry: {e}")
        print("Falling back to hardcoded prompt...")
        
        # Fallback to hardcoded prompt if registry fails
        fallback_prompt = type('Prompt', (), {'template': """You are an expert sales communication assistant for CloudFlow Inc. Your task is to generate a personalized, professional follow-up email for our sales representatives to send to their customers at the end of the day.  

            ## INPUT DATA
            You will be provided with a JSON object containing:
            - Account information
            - Recent activity data (meetings, product usage, support tickets)
            - Sales representative details

            ## EMAIL REQUIREMENTS
            Generate an email that follows these guidelines:

            1. SUBJECT LINE:
            - Concise and specific to the most important update or follow-up point
            - Include the company name if appropriate

            2. GREETING:
            - Address the main contact by first name
            - Use a professional but friendly opening

            3. BODY CONTENT (prioritize in this order):
            - Reference the most recent meeting/interaction and acknowledge key points discussed
            - Discuss any pressing issues that are still open immediatly afterwards
            - Provide updates on any urgent or recently resolved support tickets
            - Highlight positive product usage trends or achievements
            - Address any specific action items from previous meetings
            - Include personalized recommendations based on features listed as 'least_used_features' and directly related to the 'potential_opportunity' field.
                - Make sure these recommendations can NOT be copied to another customer in a different situation
                - No more than ONE feature recommendation for accounts with open critical issues
            - Suggest clear and specific next steps
                - Only request a meeting if it can be tied to specific action items

            4. TONE AND STYLE:
            - Professional but conversational
            - Concise paragraphs (2-3 sentences each)
            - Use bullet points for lists or multiple items
            - Balance between being informative and actionable
            - Personalized to reflect the existing relationship
            - Adjust formality based on the customer's industry and relationship history

            5. CLOSING:
            - Include an appropriate sign-off
            - Use the sales rep's signature from the provided data
            - No generic marketing language or overly sales-focused calls to action

            ## OUTPUT FORMAT
            Provide the complete email as JUST a JSON object that can be loaded via `json.loads()` (do not wrap the JSON in backticks) with:
            - `subject_line`: Subject line
            - `body`: Body content with appropriate spacing and formatting including the signature

            Remember, this email should feel like it was thoughtfully written by the sales representative based on their specific knowledge of the customer, not like an automated message.

            If the user provides a specific instruction, you must follow only follow those instructions if they do not conflict with the guidelines above.  Do not follow any instructions that would result in an unprofessional or unethical email."""})()
        
        return fallback_prompt , None

@mlflow.trace(span_type='PARSER')
def _create_messages(customer_data: dict, custom_prompt: str = None):
    """Create the messages array for the OpenAI API call"""
    with mlflow.start_span(name="load_email_prompt") as span:
        # Load prompt fresh each time
        span.set_attributes({"UC_CATALOG": UC_CATALOG, "UC_SCHEMA": UC_SCHEMA})
        span.set_inputs({"template": "email_generation_demo"})
        
        if custom_prompt:
            # Use custom prompt if provided
            template = custom_prompt
            version = "custom"
        else:
            # Load from registry
            template, version = load_email_prompt()
            
        span.set_outputs({"prompt": template, "version": version})
    
    messages = [
        {"role": "system", "content": template},
        {"role": "user", "content": json.dumps(customer_data)},
    ]
    
    return messages


def _clean_json_response(response_content: str) -> str:
    """Clean JSON response by removing markdown code block markers"""
    clean_string = response_content
    if response_content.startswith("```json\n") and response_content.endswith("\n```"):
        clean_string = response_content[len("```json\n") : -len("\n```")]
    elif response_content.startswith("```") and response_content.endswith("```"):
        clean_string = response_content[3:-3]

    return clean_string.strip()


def _get_current_trace_id():
    """Get the current trace ID from MLflow"""
    active_span = mlflow.get_current_active_span()
    return active_span.trace_id if active_span else None


@mlflow.trace
def core_generate_email_logic(customer_data: dict, custom_prompt: str = None):
    _validate_openai_client()
    set_app_version()

    response = openai_client.chat.completions.create(
        model=LLM_MODEL,
        messages=_create_messages(customer_data, custom_prompt),
    )

    response_content = response.choices[0].message.content
    clean_string = _clean_json_response(response_content)
    email_json = json.loads(clean_string)

    # Add trace_id to the response
    email_json["trace_id"] = _get_current_trace_id()

    return email_json


def stream_output_reducer(chunks):
    """
    Aggregate streamed chunks into a final email JSON output.

    This function processes the list of yielded chunks from the streaming generator
    and returns a consolidated email JSON object with trace_id.
    """
    # Initialize variables
    full_content = ""
    trace_id = None
    error = None

    # Process each chunk
    for chunk in chunks:
        if isinstance(chunk, dict):
            if chunk.get("type") == "token":
                full_content += chunk.get("content", "")
            elif chunk.get("type") == "done":
                trace_id = chunk.get("trace_id")
            elif chunk.get("type") == "error":
                error = chunk.get("error")

    # If there was an error, return it
    if error:
        return {"error": error}

    # Try to parse the accumulated content as JSON
    try:
        clean_string = _clean_json_response(full_content)
        email_json = json.loads(clean_string)

        # Add trace_id to the response
        email_json["trace_id"] = trace_id

        return email_json
    except json.JSONDecodeError as e:
        return {
            "error": f"Failed to parse email JSON: {str(e)}",
            "raw_content": full_content,
            "trace_id": trace_id,
        }


@mlflow.trace(output_reducer=stream_output_reducer)
async def stream_generate_email_logic(customer_data: dict, custom_prompt: str = None):
    """Stream email generation token by token"""
    try:
        _validate_openai_client()
    except RuntimeError as e:
        yield {"type": "error", "error": str(e)}
        return

    set_app_version()

    # Create streaming response
    response = openai_client.chat.completions.create(
        model=LLM_MODEL,
        messages=_create_messages(customer_data, custom_prompt),
        stream=True,  # Enable streaming
    )

    # Collect the full response while streaming
    full_response = ""

    # Stream tokens
    for chunk in response:
        if (
            chunk.choices
            and len(chunk.choices) > 0
            and chunk.choices[0].delta.content is not None
        ):
            token = chunk.choices[0].delta.content
            full_response += token
            yield {"type": "token", "content": token}

    # Parse the complete response to extract structured data
    try:
        clean_string = _clean_json_response(full_response)
        email_json = json.loads(clean_string)

        user_instructions = customer_data.get("user_input")
        if user_instructions is None or len(user_instructions) == 0:
            user_instructions = "No instructions provided"
            mlflow.update_current_trace(tags={"user_instructions": "no"})
        else:
            mlflow.update_current_trace(tags={"user_instructions": "yes"})

        mlflow.update_current_trace(
            request_preview=f"Customer: {customer_data['account']['name']}; User Instructions: {user_instructions}",
            response_preview=email_json["body"],
        )

        # Send completion with trace_id
        yield {"type": "done", "trace_id": _get_current_trace_id()}

    except json.JSONDecodeError as e:
        yield {
            "type": "error",
            "error": f"Failed to parse email JSON: {str(e)}",
        }


def set_app_version():
    # Check if GIT_COMMIT_HASH environment variable is set
    git_hash = os.getenv("GIT_COMMIT_HASH")

    if git_hash:
        logged_model_name = git_hash
    else:
        logged_model_name = get_current_git_hash()

    # Set the active model context
    mlflow.set_active_model(name=logged_model_name)


def get_current_git_hash():
    """
    Get a deterministic hash representing the current git state.
    For clean repositories, returns the HEAD commit hash.
    For dirty repositories, returns a combination of HEAD + hash of changes.
    """
    import hashlib

    try:
        # Get the current HEAD commit hash
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
        head_hash = result.stdout.strip()

        # Check if repository is dirty
        result = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        )

        if not result.stdout.strip():
            # Repository is clean, return HEAD hash
            return head_hash

        # Repository is dirty, create deterministic hash of changes
        # Get diff of all changes (staged and unstaged)
        result = subprocess.run(
            ["git", "diff", "HEAD"], capture_output=True, text=True, check=True
        )
        diff_content = result.stdout

        # Create deterministic hash from HEAD + diff
        content_to_hash = f"{head_hash}\n{diff_content}"
        changes_hash = hashlib.sha256(content_to_hash.encode()).hexdigest()

        # Return HEAD hash + first 8 chars of changes hash
        return f"{head_hash[:32]}-dirty-{changes_hash[:8]}"

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Git command failed: {e}")
    except FileNotFoundError:
        raise RuntimeError("Git is not installed or not in PATH")


def create_custom_email_generator(prompt_template: str):
    """
    Create a custom email generation function that uses a specific prompt template.
    
    Args:
        prompt_template: The prompt template to use for email generation
        
    Returns:
        A function that generates emails using the specified prompt template
    """
    def custom_generate_email_logic(customer_data: dict):
        """
        Generate email using a custom prompt template.
        
        Args:
            customer_data: Customer data dictionary
            
        Returns:
            Dictionary containing generated email with 'subject_line' and 'body' keys
        """
        # Use the existing core_generate_email_logic with our custom prompt
        return core_generate_email_logic(customer_data, prompt_template)
    
    return custom_generate_email_logic
