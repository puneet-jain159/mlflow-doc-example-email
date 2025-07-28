import mlflow
from mlflow.genai.scorers import Guidelines
from mlflow.genai import evaluate
from typing import List, Dict, Any, Optional
import json
import functools
from llm_utils import core_generate_email_logic
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


# Quality Metrics Guidelines with proper indentation
QUALITY_GUIDELINES = {
    "accuracy": """
        The response correctly references all factual content based on the provided customer data:
        
        - All factual information must be directly sourced from the provided data with NO fabrication
        - Names, dates, numbers, and company details must be 100% accurate with no errors
        - Meeting discussions must be summarized with the exact same sentiment and priority as presented in the data
        - Support ticket information must include correct ticket IDs, status, and resolution details when available
        - All product usage statistics must be presented with the same metrics provided in the data
        - No references to CloudFlow features, services, or offerings unless specifically mentioned in the customer data
        - AUTOMATIC FAIL if any information is mentioned that is not explicitly provided in the data
    """,
    
    "personalized": """
        The response demonstrates clear personalization based on the provided customer data:
        
        - Email must begin by referencing the most recent meeting/interaction
        - Immediately next, the email must address the customer's MOST pressing concern as evidenced in the data
        - Content structure must be customized based on the account's health status (critical issues first for "Fair" or "Poor" accounts)
        - Industry-specific language must be used that reflects the customer's sector
        - Recommendations must ONLY reference features that are:
            a) Listed as "least_used_features" in the data, AND
            b) Directly related to the "potential_opportunity" field
        - Relationship history must be acknowledged (new vs. mature relationship)
        - Deal stage must influence communication approach (implementation vs. renewal vs. growth)
        - AUTOMATIC FAIL if recommendations could be copied to another customer in a different situation
    """,
    
    "relevance": """
        The response prioritizes content that matters to the recipient in the provided customer data:
        
        - Critical support tickets (status="Open (Critical)") must be addressed after the greeting, reference to the most recent interaction, any pleasantries, and references to closed tickets
        - Time-sensitive action items must be addressed before general updates
        - Content must be ordered by descending urgency as defined by:
            1. Critical support issues
            2. Action items explicitly stated in most recent meeting
            3. Upcoming renewal if within 30 days
            4. Recently resolved issues
            5. Usage trends and recommendations
        - No more than ONE feature recommendation for accounts with open critical issues
        - No mentions of company news, product releases, or success stories not directly requested by the customer
        - No calls to action unrelated to the immediate needs in the data
        - AUTOMATIC FAIL if the email requests a meeting without being tied to a specific action item or opportunity in the data
    """,
    
    "professional_tone": """
        The response maintains appropriate professional tone and style:
        
        - Professional but conversational tone throughout
        - Concise paragraphs (2-3 sentences each)
        - Use bullet points for lists or multiple items
        - Balance between being informative and actionable
        - Personalized to reflect the existing relationship
        - Adjust formality based on the customer's industry and relationship history
        - No overly sales-focused or pushy language
        - Appropriate greeting and closing structure
        - Sales rep signature included as provided in the data
    """,
    
    "completeness": """
        The response addresses all key elements from the customer data:
        
        - References the most recent meeting/interaction
        - Addresses any open support tickets or issues
        - Includes relevant product usage trends
        - Mentions specific action items from previous interactions
        - Provides personalized recommendations when appropriate
        - Includes clear next steps or calls to action
        - Proper subject line that reflects the most important content
        - Complete email structure with greeting, body, and closing
    """
}


def create_guidelines_scorers() -> List[Guidelines]:
    """
    Create Guidelines scorers for quality assessment.
    
    Returns:
        List of Guidelines scorers for each quality metric
    """
    scorers = []
    for metric_name, guideline in QUALITY_GUIDELINES.items():
        scorer = Guidelines(
            name=metric_name,
            guidelines=guideline.strip()
        )
        scorers.append(scorer)
    return scorers


def create_custom_guidelines_scorers(custom_guidelines: Dict[str, str]) -> List[Guidelines]:
    """
    Create Guidelines scorers from custom guidelines.
    
    Args:
        custom_guidelines: Dictionary of guideline names to guideline content
        
    Returns:
        List of Guidelines scorers for each custom metric
    """
    scorers = []
    for metric_name, guideline in custom_guidelines.items():
        scorer = Guidelines(
            name=metric_name,
            guidelines=guideline.strip()
        )
        scorers.append(scorer)
    return scorers


def email_generation_app(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Prediction function for email generation that can be used with MLflow evaluation.
    
    Args:
        inputs: Dictionary containing customer information
        
    Returns:
        Dictionary containing generated email with 'body' key
    """
    # Generate email using the existing logic
    email_result = core_generate_email_logic(inputs)
    
    # Return in format expected by evaluation
    return {
        "body": email_result.get("body", ""),
        "subject_line": email_result.get("subject_line", "")
    }


def format_trace_data_for_evaluation(traces):
    """
    Format trace data for MLflow evaluation.
    
    Args:
        traces: DataFrame from mlflow.search_traces()
        
    Returns:
        List of formatted data for evaluation
    """
    formatted_data = []
    
    for _, trace in traces.iterrows():
        # Extract customer data from the 'request' column
        request_data = trace.get('request', {})
        customer_data = request_data.get('customer_data', request_data)
        
        # Format following the pattern: {"inputs": {"inputs": {...}}}
        formatted_data.append({
            "inputs": {"inputs": customer_data}
        })
    
    return formatted_data


def run_quality_assessment(
    max_traces: int = 5,
    custom_predict_fn: Optional[callable] = None,
    custom_scorers: Optional[List] = None,
    custom_guidelines: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Run quality assessment on recent production traces.
    
    Args:
        max_traces: Maximum number of traces to evaluate (default: 5)
        custom_predict_fn: Custom prediction function (default: uses email_generation_app)
        custom_scorers: Custom list of scorers (default: uses quality guidelines)
        
    Returns:
        Evaluation results from MLflow
    """
    # Get recent traces
    traces = mlflow.search_traces(
        max_results=max_traces, 
        order_by=['attributes.timestamp_ms DESC']
    )
    
    print(f"Found {len(traces)} traces for evaluation")
    
    # Format trace data for evaluation
    formatted_data = format_trace_data_for_evaluation(traces)
    print(f"Formatted {len(formatted_data)} traces for evaluation")
    
    # Use default predict function if none provided
    predict_fn = custom_predict_fn or email_generation_app
    
    # Use custom guidelines if provided, otherwise use default scorers
    if custom_guidelines:
        scorers = create_custom_guidelines_scorers(custom_guidelines)
    else:
        scorers = custom_scorers or create_guidelines_scorers()
    
    # Run evaluation
    results = evaluate(
        data=formatted_data,
        predict_fn=predict_fn,
        scorers=scorers
    )
    
    return results





def get_quality_metrics_summary(results) -> Dict[str, Any]:
    """
    Extract and summarize quality metrics from evaluation results.
    
    Args:
        results: Evaluation results from MLflow
        
    Returns:
        Dictionary containing summarized quality metrics
    """
    # Initialize summary with defaults
    summary = {
        "overall_score": 0.0,
        "metrics": {},
        "total_evaluations": 0,
        "passed_evaluations": 0
    }
    
    # Extract metrics efficiently
    if hasattr(results, 'metrics') and results.metrics:
        # Filter for quality metrics (exclude agent metrics)
        quality_metrics = {
            name: value for name, value in results.metrics.items() 
            if not name.startswith('agent/')
        }
        
        if quality_metrics:
            # Convert numpy values to float and calculate scores
            scores = []
            for metric_name, metric_value in quality_metrics.items():
                score = float(metric_value.item() if hasattr(metric_value, 'item') else metric_value)
                summary["metrics"][metric_name] = {"score": score, "rationale": ""}
                scores.append(score)
            
            # Calculate overall quality score (average of quality metrics only)
            summary["overall_score"] = sum(scores) / len(scores)
    
    # Extract evaluation count
    if hasattr(results, 'tables') and 'eval_results' in results.tables:
        eval_count = len(results.tables['eval_results'])
        summary["total_evaluations"] = eval_count
        summary["passed_evaluations"] = eval_count
    
    return summary





if __name__ == "__main__":
    # Example usage
    print("Running quality assessment on recent traces...")
    results = run_quality_assessment(max_traces=3)
    summary = get_quality_metrics_summary(results)
    
    print(f"Overall Quality Score: {summary['overall_score']:.2f}")
    print("\nIndividual Metrics:")
    for metric, data in summary["metrics"].items():
        print(f"  {metric}: {data['score']:.2f}") 