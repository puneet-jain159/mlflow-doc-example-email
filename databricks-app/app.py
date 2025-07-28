from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, AsyncGenerator, List, Dict, Any
from enum import Enum
import json
import os
import mlflow
import asyncio
import uvicorn

# Import from the llm_utils module
from llm_utils import (
    core_generate_email_logic,
    set_app_version,
    openai_client,
    stream_generate_email_logic,
)

# Import quality metrics functionality
from quality_metrics import (
    run_quality_assessment,
    get_quality_metrics_summary,
    QUALITY_GUIDELINES
)


# Load customer data from input_data.jsonl
def load_customer_data():
    customers = []
    try:
        with open("input_data.jsonl", "r") as f:
            for line in f:
                customers.append(json.loads(line))
    except FileNotFoundError:
        # Try alternative path if run from different directory
        try:
            with open("input_data.jsonl", "r") as f:
                for line in f:
                    customers.append(json.loads(line))
        except FileNotFoundError:
            print("Warning: input_data.jsonl not found")
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
    env_vars = {
        "DATABRICKS_HOST": os.getenv("DATABRICKS_HOST"),
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
    """
    Health check for quality assessment functionality
    """
    try:
        # Test if we can access the guidelines
        guidelines_count = len(QUALITY_GUIDELINES)
        
        return {
            "status": "healthy",
            "guidelines_loaded": True,
            "guidelines_count": guidelines_count,
            "available_metrics": list(QUALITY_GUIDELINES.keys())
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


# Mount static files - this must be after all API routes
# Check if static directory exists before mounting
if os.path.exists("static"):
    app.mount("/", StaticFiles(directory="static", html=True), name="static")


PORT = int(os.getenv("UVICORN_PORT", 8000))
HOST = os.getenv("UVICORN_HOST", "0.0.0.0")

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)
