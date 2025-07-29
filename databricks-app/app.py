import os
import json
import asyncio
from datetime import datetime
from typing import Dict, Any, Optional
from enum import Enum
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
import openai
from openai import AsyncOpenAI
import mlflow
from llm_utils import load_email_prompt, core_generate_email_logic, stream_generate_email_logic
from quality_metrics import run_quality_assessment, get_quality_metrics_summary


# Import from the llm_utils module
from llm_utils import (
    core_generate_email_logic,
    set_app_version,
    openai_client,
    stream_generate_email_logic,
    load_email_prompt,
)

# Import quality metrics functionality
from quality_metrics import (
    run_quality_assessment,
    get_quality_metrics_summary,
    QUALITY_GUIDELINES
)


from tracing import (
  setup_mlflow_tracing
)


def ensure_databricks_host_protocol():
    """Ensure DATABRICKS_HOST has https:// protocol if not already present"""
    databricks_host = os.getenv("DATABRICKS_HOST")
    if databricks_host:
        # Check if the host already has a protocol
        if not databricks_host.startswith(("http://", "https://")):
            # Add https:// protocol
            os.environ["DATABRICKS_HOST"] = f"https://{databricks_host}"
            print(f"Added https:// protocol to DATABRICKS_HOST: {os.environ['DATABRICKS_HOST']}")
        elif databricks_host.startswith("http://"):
            # Convert http:// to https:// for security
            os.environ["DATABRICKS_HOST"] = databricks_host.replace("http://", "https://", 1)
            print(f"Converted http:// to https:// for DATABRICKS_HOST: {os.environ['DATABRICKS_HOST']}")
        else:
            print(f"DATABRICKS_HOST already has https:// protocol: {databricks_host}")
    else:
        print("Warning: DATABRICKS_HOST environment variable not set")


def get_databricks_host():
    """Get the DATABRICKS_HOST with proper https:// protocol"""
    databricks_host = os.getenv("DATABRICKS_HOST")
    if databricks_host:
        # Ensure it has https:// protocol
        if not databricks_host.startswith(("http://", "https://")):
            return f"https://{databricks_host}"
        elif databricks_host.startswith("http://"):
            # Convert http:// to https:// for security
            return databricks_host.replace("http://", "https://", 1)
        else:
            return databricks_host
    return None




# Load customer data from gsk_10_accounts.jsonl
def load_customer_data():
    customers = []
    try:
        with open("gsk_10_accounts.jsonl", "r") as f:
            for line in f:
                customers.append(json.loads(line))
    except FileNotFoundError:
        # Try alternative path if run from different directory
        try:
            with open("../gsk_10_accounts.jsonl", "r") as f:
                for line in f:
                    customers.append(json.loads(line))
        except FileNotFoundError:
            print("Warning: gsk_10_accounts.jsonl not found")
    return customers


CUSTOMER_DATA = load_customer_data()


class EmailRequest(BaseModel):
    customer_info: dict


class EmailOutput(BaseModel):
    subject_line: str
    body: str
    trace_id: Optional[str] = None


class FeedbackRating(str, Enum):
    THUMBS_UP = "up"
    THUMBS_DOWN = "down"


class FeedbackRequest(BaseModel):
    trace_id: str
    rating: FeedbackRating
    comment: Optional[str] = None
    sales_rep_name: Optional[str] = None


class FeedbackResponse(BaseModel):
    success: bool
    message: str


class QualityAssessmentRequest(BaseModel):
    max_traces: Optional[int] = 5
    custom_guidelines: Optional[Dict[str, str]] = None


class QualityMetricsResponse(BaseModel):
    overall_score: float
    metrics: Dict[str, Dict[str, Any]]
    total_evaluations: int
    passed_evaluations: int
    assessment_type: str
    timestamp: str
    run_id: Optional[str] = None


class GuidelinesResponse(BaseModel):
    guidelines: Dict[str, str]


class PromptEvaluationRequest(BaseModel):
    baseline_prompt: str
    new_prompt: str
    customer_data: Optional[Dict[str, Any]] = None


class PromptEvaluationResponse(BaseModel):
    baseline_score: Optional[float] = None
    new_score: Optional[float] = None
    improvement: Optional[str] = None
    run_id: Optional[str] = None
    baseline_run_id: Optional[str] = None
    error: Optional[str] = None


class BaselinePromptResponse(BaseModel):
    prompt: str
    version: Optional[str] = None
    source: str  # 'registry' or 'fallback'
    error: Optional[str] = None


class PromptTestRequest(BaseModel):
    prompt: str
    customer_data: Optional[Dict[str, Any]] = None


class PromptTestResponse(BaseModel):
    score: Optional[float] = None
    metrics: Optional[Dict[str, Dict[str, Any]]] = None
    run_id: Optional[str] = None
    error: Optional[str] = None


app = FastAPI()

# Enable CORS for frontend to access backend APIs
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "*",  # Added for Databricks compatibility
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure DATABRICKS_HOST has proper protocol
ensure_databricks_host_protocol()
setup_mlflow_tracing()



@app.get("/api/hello")
async def query():
    return "Hello, world!"


@app.post("/api/generate-email/", response_model=EmailOutput)
async def api_generate_email(request_data: EmailRequest):
    customer_data_dict = request_data.customer_info
    try:
        set_app_version()
        email_json = core_generate_email_logic(customer_data_dict)
        if (
            not isinstance(email_json, dict)
            or "subject_line" not in email_json
            or "body" not in email_json
        ):
            raise ValueError(
                "LLM output is not in the expected format (missing 'subject_line' or 'body')"
            )
        return EmailOutput(**email_json)
    except Exception as e:
        error_msg = str(e)
        if "OpenAI client not available" in error_msg:
            status_code = 503
        elif "Failed to parse LLM output" in error_msg:
            status_code = 500
        else:
            status_code = 500
        raise HTTPException(status_code=status_code, detail=error_msg)


@app.post("/api/generate-email-stream/")
async def api_generate_email_stream(request_data: EmailRequest):
    """Stream email generation token by token using Server-Sent Events"""
    customer_data_dict = request_data.customer_info
    set_app_version()

    async def generate():
        try:
            # Stream tokens from the LLM
            async for chunk in stream_generate_email_logic(customer_data_dict):
                # Format as Server-Sent Event
                if chunk["type"] == "token":
                    yield f"data: {json.dumps({'type': 'token', 'content': chunk['content']})}\n\n"
                elif chunk["type"] == "done":
                    yield f"data: {json.dumps({'type': 'done', 'trace_id': chunk['trace_id']})}\n\n"
                elif chunk["type"] == "error":
                    yield f"data: {json.dumps({'type': 'error', 'error': chunk['error']})}\n\n"

                # Small delay to ensure smooth streaming
                await asyncio.sleep(0.01)
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"
        finally:
            # Send done event to close the stream
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        },
    )


@app.get("/api/health")
async def health_check():
    return {
        "status": "ok",
        # Use the imported openai_client for the health check
        "openai_client_initialized": openai_client is not None,
    }


@app.get("/api/env-check")
async def env_check():
    """Endpoint to verify environment variables are loaded correctly"""
    databricks_host = os.getenv("DATABRICKS_HOST")
    
    # Check if DATABRICKS_HOST has proper protocol
    protocol_status = "unknown"
    if databricks_host:
        if databricks_host.startswith("https://"):
            protocol_status = "https_secure"
        elif databricks_host.startswith("http://"):
            protocol_status = "http_insecure"
        else:
            protocol_status = "no_protocol"
    
    env_vars = {
        "DATABRICKS_HOST": databricks_host,
        "MLFLOW_TRACKING_URI": os.getenv("MLFLOW_TRACKING_URI"),
        "MLFLOW_EXPERIMENT_ID": os.getenv("MLFLOW_EXPERIMENT_ID"),
        "LLM_MODEL": os.getenv("LLM_MODEL"),
        # Don't expose the actual token, just check if it exists
        "DATABRICKS_TOKEN": "***" if os.getenv("DATABRICKS_TOKEN") else None,
    }
    return {
        "status": "ok",
        "environment_variables": env_vars,
        "all_vars_present": all(v is not None for v in env_vars.values()),
        "databricks_host_protocol_status": protocol_status,
        "databricks_host_has_protocol": databricks_host.startswith(("http://", "https://")) if databricks_host else False,
    }


@app.get("/api/databricks-host-check")
async def databricks_host_check():
    """Endpoint to specifically check DATABRICKS_HOST configuration"""
    original_host = os.getenv("DATABRICKS_HOST")
    processed_host = get_databricks_host()
    
    return {
        "original_databricks_host": original_host,
        "processed_databricks_host": processed_host,
        "has_protocol": original_host.startswith(("http://", "https://")) if original_host else False,
        "is_secure": original_host.startswith("https://") if original_host else False,
        "was_modified": original_host != processed_host if original_host and processed_host else False,
        "status": "configured" if processed_host else "not_set"
    }


@app.get("/api/companies")
async def get_companies():
    """Get list of all company names"""
    companies = [{"name": customer["account"]["name"]} for customer in CUSTOMER_DATA]
    return sorted(companies, key=lambda x: x["name"])


@app.get("/api/customer/{company_name}")
async def get_customer_by_name(company_name: str):
    """Get customer data by company name"""
    for customer in CUSTOMER_DATA:
        if customer["account"]["name"] == company_name:
            return customer
    raise HTTPException(status_code=404, detail=f"Company '{company_name}' not found")


@app.get("/api/sample-customers")
async def get_sample_customers(limit: int = 3):
    """Get sample customer data for testing prompt evaluation"""
    if limit > len(CUSTOMER_DATA):
        limit = len(CUSTOMER_DATA)
    
    sample_customers = CUSTOMER_DATA[:limit]
    return {
        "customers": sample_customers,
        "total_available": len(CUSTOMER_DATA),
        "sample_size": limit
    }


@app.post("/api/feedback", response_model=FeedbackResponse)
async def submit_feedback(feedback: FeedbackRequest):
    """
    Submit user feedback linked to trace
    """
    try:
        # Log feedback using mlflow.log_feedback (MLflow 3 API)
        mlflow.log_feedback(
            trace_id=feedback.trace_id,
            name="user_feedback",
            value=True if feedback.rating == FeedbackRating.THUMBS_UP else False,
            rationale=feedback.comment if feedback.comment else None,
            source=mlflow.entities.AssessmentSource(
                source_type="HUMAN",
                source_id=feedback.sales_rep_name or "user",
            ),
        )

        return FeedbackResponse(success=True, message="Feedback submitted successfully")

    except Exception as e:
        return FeedbackResponse(
            success=False, message=f"Error submitting feedback: {str(e)}"
        )


@app.post("/api/quality-assessment", response_model=QualityMetricsResponse)
async def run_quality_assessment_api(request: QualityAssessmentRequest):
    """
    Run quality assessment on recent production traces with optional custom guidelines
    """
    try:
        import datetime
        
        # Run assessment on recent traces with custom guidelines if provided
        results = run_quality_assessment(
            max_traces=request.max_traces,
            custom_guidelines=request.custom_guidelines
        )
        assessment_type = "production_traces"
        
        # Get summary of results
        summary = get_quality_metrics_summary(results)
        summary["assessment_type"] = assessment_type
        summary["timestamp"] = datetime.datetime.now().isoformat()
        
        # Add run_id to response
        if hasattr(results, 'run_id'):
            summary["run_id"] = results.run_id
        
        return QualityMetricsResponse(**summary)
        
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Error running quality assessment: {str(e)}"
        )


@app.get("/api/quality-guidelines", response_model=GuidelinesResponse)
async def get_quality_guidelines():
    """
    Get the current quality assessment guidelines
    """
    return GuidelinesResponse(guidelines=QUALITY_GUIDELINES)


@app.get("/api/quality-assessment/health")
async def quality_assessment_health():
    """Health check for quality assessment functionality"""
    try:
        # Test basic functionality
        test_guidelines = {"test": "Test guideline"}
        result = await run_quality_assessment_api(QualityAssessmentRequest(
            max_traces=1,
            custom_guidelines=test_guidelines
        ))
        return {"status": "healthy", "message": "Quality assessment is working"}
    except Exception as e:
        return {"status": "unhealthy", "message": str(e)}


@app.post("/api/evaluate-prompt", response_model=PromptEvaluationResponse)
async def evaluate_prompt(request: PromptEvaluationRequest):
    """Evaluate a new prompt against a baseline prompt using quality assessment framework"""
    try:
        from llm_utils import create_custom_email_generator
        from quality_metrics import create_guidelines_scorers, evaluate, get_quality_metrics_summary
        
        # Ensure prompts are strings
        baseline_prompt = str(request.baseline_prompt) if request.baseline_prompt else ""
        new_prompt = str(request.new_prompt) if request.new_prompt else ""
        
        # Get some sample customer data for evaluation
        if request.customer_data:
            sample_data = [request.customer_data]
        else:
            # Use first few customers from our data as test cases
            sample_data = CUSTOMER_DATA[:3] if len(CUSTOMER_DATA) >= 3 else CUSTOMER_DATA
        
        if not sample_data:
            raise ValueError("No customer data available for evaluation")
        
        # Create custom generators for baseline and new prompt
        baseline_generator = create_custom_email_generator(baseline_prompt)
        new_generator = create_custom_email_generator(new_prompt)
        
        # Create prediction functions for evaluation
        def baseline_predict_fn(inputs):
            """Prediction function using baseline prompt"""
            result = baseline_generator(inputs.get("inputs", inputs))
            return {
                "body": result.get("body", ""),
                "subject_line": result.get("subject_line", "")
            }
        
        def new_predict_fn(inputs):
            """Prediction function using new prompt"""
            result = new_generator(inputs.get("inputs", inputs))
            return {
                "body": result.get("body", ""),
                "subject_line": result.get("subject_line", "")
            }
        
        # Format data for evaluation
        formatted_data = [{"inputs": {"inputs": customer}} for customer in sample_data]
        
        # Get quality guidelines scorers
        scorers = create_guidelines_scorers()
        
        # Run evaluation for baseline prompt
        baseline_results = evaluate(
            data=formatted_data,
            predict_fn=baseline_predict_fn,
            scorers=scorers
        )
        
        # Format data for evaluation
        formatted_data = [{"inputs": {"inputs": customer}} for customer in sample_data]

        # Run evaluation for new prompt
        new_results = evaluate(
            data=formatted_data,
            predict_fn=new_predict_fn,
            scorers=scorers
        )
        
        # Get summaries using the proper function
        baseline_summary = get_quality_metrics_summary(baseline_results)
        new_summary = get_quality_metrics_summary(new_results)
        
        # Calculate scores
        baseline_score = baseline_summary.get("overall_score", 0.0)
        new_score = new_summary.get("overall_score", 0.0)
        
        # Determine improvement
        score_diff = new_score - baseline_score
        if score_diff > 0.1:
            improvement = "significant_improvement"
        elif score_diff > 0.05:
            improvement = "moderate_improvement"
        elif score_diff > 0:
            improvement = "slight_improvement"
        elif score_diff < -0.1:
            improvement = "significant_decline"
        elif score_diff < -0.05:
            improvement = "moderate_decline"
        elif score_diff < 0:
            improvement = "slight_decline"
        else:
            improvement = "no_change"
        
        # Get run_id from the evaluation results
        run_id = getattr(new_results, 'run_id', None)
        baseline_run_id = getattr(baseline_results, 'run_id', None)
        
        return PromptEvaluationResponse(
            baseline_score=baseline_score,
            new_score=new_score,
            improvement=improvement,
            run_id=run_id,
            baseline_run_id=baseline_run_id
        )
        
    except Exception as e:
        return PromptEvaluationResponse(
            error=f"Error evaluating prompts: {str(e)}"
        )


@app.get("/api/baseline-prompt", response_model=BaselinePromptResponse)
async def get_baseline_prompt():
    """Fetch the baseline prompt from MLflow registry"""
    try:
        # Load the prompt from the registry
        prompt_template, prompt_version = load_email_prompt()
        
        # Ensure the prompt is properly formatted as a string
        if isinstance(prompt_template, str):
            # If the prompt appears to be a JSON string, parse it
            if prompt_template.startswith('"') and prompt_template.endswith('"'):
                import json
                try:
                    prompt_template = json.loads(prompt_template)
                except json.JSONDecodeError:
                    # If JSON parsing fails, just clean up the escaping
                    prompt_template = prompt_template.replace('\\n', '\n').replace('\\"', '"')
                    if prompt_template.startswith('"') and prompt_template.endswith('"'):
                        prompt_template = prompt_template[1:-1]
            else:
                # Clean up any extra escaping that might have occurred
                prompt_template = prompt_template.replace('\\n', '\n').replace('\\"', '"')
        
        return BaselinePromptResponse(
            prompt=prompt_template,
            version=str(prompt_version) if prompt_version is not None else None,
            source="registry"
        )
        
    except Exception as e:
        return BaselinePromptResponse(
            prompt="",  # Empty prompt on error
            version=None,
            source="fallback",
            error=f"Failed to load prompt from registry: {str(e)}"
        )


@app.post("/api/test-prompt", response_model=PromptTestResponse)
async def test_single_prompt(request: PromptTestRequest):
    """Test a single prompt and get its quality score using quality assessment framework"""
    try:
        from llm_utils import create_custom_email_generator
        from quality_metrics import create_guidelines_scorers, evaluate, get_quality_metrics_summary
        
        # Get sample customer data for evaluation
        if request.customer_data:
            sample_data = [request.customer_data]
        else:
            # Use first few customers from our data as test cases
            sample_data = CUSTOMER_DATA[:3] if len(CUSTOMER_DATA) >= 3 else CUSTOMER_DATA
        
        if not sample_data:
            raise ValueError("No customer data available for evaluation")
        
        # Create custom generator for the test prompt
        test_generator = create_custom_email_generator(request.prompt)
        
        # Create prediction function for evaluation
        def test_predict_fn(inputs):
            """Prediction function using test prompt"""
            result = test_generator(inputs.get("inputs", inputs))
            return {
                "body": result.get("body", ""),
                "subject_line": result.get("subject_line", "")
            }
        
        # Format data for evaluation
        formatted_data = [{"inputs": {"inputs": customer}} for customer in sample_data]
        
        # Get quality guidelines scorers
        scorers = create_guidelines_scorers()
        
        # Run evaluation for the test prompt
        results = evaluate(
            data=formatted_data,
            predict_fn=test_predict_fn,
            scorers=scorers
        )
        
        # Get summary using the proper function
        summary = get_quality_metrics_summary(results)
        
        # Extract scores
        score = summary.get("overall_score", 0.0)
        metrics = summary.get("metrics", {})
        run_id = getattr(results, 'run_id', None)
        
        return PromptTestResponse(
            score=score,
            metrics=metrics,
            run_id=run_id
        )
        
    except Exception as e:
        return PromptTestResponse(
            error=f"Error testing prompt: {str(e)}"
        )


# Mount static files - this must be after all API routes
# Check if static directory exists before mounting
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")


PORT = int(os.getenv("UVICORN_PORT", 8000))
HOST = os.getenv("UVICORN_HOST", "0.0.0.0")

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
