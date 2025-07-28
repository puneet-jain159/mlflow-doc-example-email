import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import './App.css';

function App() {
  const [companies, setCompanies] = useState([]);
  const [selectedCompany, setSelectedCompany] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [showDropdown, setShowDropdown] = useState(false);
  const [customerData, setCustomerData] = useState(null);
  const [userInstructions, setUserInstructions] = useState('');
  const [generatedEmail, setGeneratedEmail] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingCompanies, setLoadingCompanies] = useState(true);
  const [error, setError] = useState(null);
  const [backendStatus, setBackendStatus] = useState("Checking backend...");
  const [envStatus, setEnvStatus] = useState(null);
  // Feedback state
  const [feedbackRating, setFeedbackRating] = useState(null); // 'up' or 'down'
  const [feedbackComment, setFeedbackComment] = useState('');
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  const [currentTraceId, setCurrentTraceId] = useState(null); // Store trace_id
  // Streaming state
  const [streamingContent, setStreamingContent] = useState(''); // Raw streaming content
  const [isStreaming, setIsStreaming] = useState(false); // Streaming in progress
  const [streamingEmail, setStreamingEmail] = useState({ subject_line: '', body: '' }); // Parsed streaming email
  // Sidebar state
  const [activeTab, setActiveTab] = useState('demo-overview');
  const [sidebarOpen, setSidebarOpen] = useState(true);
  
  // Quality assessment state
  const [qualityGuidelines, setQualityGuidelines] = useState({
    accuracy: `The response correctly references all factual information from the provided_info based on these rules:

• All factual information must be directly sourced from the provided data with NO fabrication
• Names, dates, numbers, and company details must be 100% accurate with no errors
• Meeting discussions must be summarized with the exact same sentiment and priority as presented in the data
• Support ticket information must include correct ticket IDs, status, and resolution details when available
• All product usage statistics must be presented with the same metrics provided in the data
• No references to CloudFlow features, services, or offerings unless specifically mentioned in the customer data
• AUTOMATIC FAIL if any information is mentioned that is not explicitly provided in the data`,
    personalized: `The response demonstrates clear personalization based on the provided_info based on these rules:

• Email must begin by referencing the most recent meeting/interaction
• Immediatly next, the email must address the customer's MOST pressing concern as evidenced in the data
• Content structure must be customized based on the account's health status (critical issues first for "Fair" or "Poor" accounts)
• Industry-specific language must be used that reflects the customer's sector
• Recommendations must ONLY reference features that are:
  a) Listed as "least_used_features" in the data, AND
  b) Directly related to the "potential_opportunity" field
• Relationship history must be acknowledged (new vs. mature relationship)`
  });
  const [assessmentResults, setAssessmentResults] = useState(null);
  const [assessmentLoading, setAssessmentLoading] = useState(false);
  const [assessmentError, setAssessmentError] = useState(null);
  const [mlflowConfig, setMlflowConfig] = useState(null);

  useEffect(() => {
    // Check backend health
    axios.get('/api/health')
      .then(response => {
        if (response.data.status === 'ok') {
          const clientStatus = response.data.openai_client_initialized ? "Databricks OpenAI client initialized." : "Mock OpenAI client active.";
          setBackendStatus(`Backend is running. ${clientStatus}`);
        } else {
          setBackendStatus("Backend status unknown.");
        }
      })
      .catch(err => {
        console.error("Health check failed:", err);
        setBackendStatus("Backend not reachable. Please start the backend server.");
      });

    // Check backend environment variables
    fetch('/api/env-check')
      .then(response => response.json())
      .then(data => {
        setEnvStatus(data);
        console.log('Backend environment variables:', data);
      })
      .catch(error => {
        console.error('Error checking environment variables:', error);
        setEnvStatus({ error: error.message });
      });

    // Load companies
    loadCompanies();
    
    // Load MLflow configuration
    loadMlflowConfig();
  }, []);

  const loadCompanies = async () => {
    try {
      setLoadingCompanies(true);
      const response = await axios.get('/api/companies');
      setCompanies(response.data);
    } catch (err) {
      console.error("Error loading companies:", err);
      setError("Failed to load companies");
    } finally {
      setLoadingCompanies(false);
    }
  };

  const handleCompanySelect = async (companyName) => {
    setSelectedCompany(companyName);
    setSearchQuery(companyName);
    setShowDropdown(false);
    setUserInstructions(''); // Reset instructions when changing companies
    
    if (!companyName) {
      setCustomerData(null);
      return;
    }

    try {
      const response = await axios.get(`/api/customer/${encodeURIComponent(companyName)}`);
      setCustomerData(response.data);
      setError(null);
    } catch (err) {
      console.error("Error loading customer data:", err);
      setError("Failed to load customer data");
      setCustomerData(null);
    }
  };

  const handleSearchChange = (e) => {
    const value = e.target.value;
    setSearchQuery(value);
    setShowDropdown(true);
    
    // If search is cleared, also clear selection
    if (!value) {
      setSelectedCompany('');
      setCustomerData(null);
    }
  };

  const filteredCompanies = companies.filter(company =>
    company.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  const updateNestedField = (path, value) => {
    setCustomerData(prev => {
      const newData = JSON.parse(JSON.stringify(prev)); // Deep copy
      const keys = path.split('.');
      let current = newData;
      
      for (let i = 0; i < keys.length - 1; i++) {
        current = current[keys[i]];
      }
      
      current[keys[keys.length - 1]] = value;
      return newData;
    });
  };

  const handleGenerateEmail = async () => {
    if (!customerData) return;
    
    // Always use streaming for better UX
    await handleGenerateEmailStream();
  };

  const handleGenerateEmailStream = async () => {
    if (!customerData) return;
    
    setIsStreaming(true);
    setError(null);
    setGeneratedEmail(null);
    setStreamingContent('');
    setStreamingEmail({ subject_line: '', body: '' });
    // Reset feedback state for new generation
    setFeedbackRating(null);
    setFeedbackComment('');
    setFeedbackSubmitted(false);
    setCurrentTraceId(null);
    
    try {
      const response = await fetch('/api/generate-email-stream/', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          customer_info: {
            ...customerData,
            user_instructions: userInstructions
          }
        }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let accumulatedContent = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              
              if (data.type === 'token') {
                accumulatedContent += data.content;
                setStreamingContent(accumulatedContent);
                
                // Try to parse partial JSON to extract subject and body
                parsePartialEmail(accumulatedContent);
              } else if (data.type === 'done') {
                if (data.trace_id) {
                  setCurrentTraceId(data.trace_id);
                }
                // Parse the final content to extract subject and body
                try {
                  let cleanContent = accumulatedContent;
                  if (cleanContent.startsWith('```json')) {
                    cleanContent = cleanContent.replace(/^```json\n/, '').replace(/\n```$/, '');
                  }
                  const parsedEmail = JSON.parse(cleanContent);
                  setGeneratedEmail(parsedEmail);
                } catch (parseError) {
                  console.error('Error parsing final email:', parseError);
                  setError('Failed to parse generated email');
                }
              } else if (data.type === 'error') {
                setError(data.error || 'An error occurred during generation');
              }
            } catch (parseError) {
              console.error('Error parsing streaming data:', parseError);
            }
          }
        }
      }
    } catch (err) {
      console.error("Error generating email stream:", err);
      setError(err.message || "Failed to generate email");
    } finally {
      setIsStreaming(false);
    }
  };

  const parsePartialEmail = (content) => {
    try {
      // Try to extract JSON from the content
      let jsonContent = content;
      if (content.includes('```json')) {
        jsonContent = content.split('```json')[1]?.split('```')[0] || content;
      }
      
      // Try to parse as JSON
      const parsed = JSON.parse(jsonContent);
      if (parsed.subject_line) {
        setStreamingEmail(prev => ({ ...prev, subject_line: parsed.subject_line }));
      }
      if (parsed.body) {
        // Convert markdown to HTML for streaming preview
        const htmlBody = renderMarkdown(parsed.body);
        setStreamingEmail(prev => ({ ...prev, body: parsed.body }));
      }
    } catch (error) {
      // Ignore parsing errors for partial content
    }
  };

  const handleFeedbackRating = (rating) => {
    setFeedbackRating(rating);
  };

  const renderMarkdown = (text) => {
    if (!text) return '';
    
    // Simple markdown to HTML conversion
    return text
      // Headers
      .replace(/^### (.*$)/gim, '<h3>$1</h3>')
      .replace(/^## (.*$)/gim, '<h2>$1</h2>')
      .replace(/^# (.*$)/gim, '<h1>$1</h1>')
      // Bold
      .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
      // Italic
      .replace(/\*(.*?)\*/g, '<em>$1</em>')
      // Links
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
      // Line breaks
      .replace(/\n\n/g, '</p><p>')
      .replace(/\n/g, '<br>')
      // Wrap in paragraphs
      .replace(/^(.+)$/gm, '<p>$1</p>')
      // Clean up empty paragraphs
      .replace(/<p><\/p>/g, '')
      .replace(/<p><br><\/p>/g, '<br>');
  };

  const handleFeedbackSubmit = async () => {
    if (!feedbackRating || !currentTraceId) return;
    
    setFeedbackSubmitted(true);
    
    try {
      const response = await axios.post('/api/feedback', {
        trace_id: currentTraceId,
        rating: feedbackRating,
        comment: feedbackComment,
        sales_rep_name: customerData?.sales_rep?.name || 'user'
      });
      
      if (response.data.success) {
        console.log('Feedback submitted successfully:', response.data.message);
      } else {
        console.error('Feedback submission failed:', response.data.message);
        setFeedbackSubmitted(false);
      }
    } catch (err) {
      console.error('Error submitting feedback:', err);
      setFeedbackSubmitted(false);
    }
  };

  const handleGuidelineUpdate = (guidelineName, newContent) => {
    setQualityGuidelines(prev => ({
      ...prev,
      [guidelineName]: newContent
    }));
  };

  const handleAddGuideline = () => {
    const newGuidelineName = `guideline_${Object.keys(qualityGuidelines).length + 1}`;
    setQualityGuidelines(prev => ({
      ...prev,
      [newGuidelineName]: "Enter your custom guideline here..."
    }));
  };

  const handleRemoveGuideline = (guidelineName) => {
    setQualityGuidelines(prev => {
      const newGuidelines = { ...prev };
      delete newGuidelines[guidelineName];
      return newGuidelines;
    });
  };

  const handleRunAssessment = async () => {
    setAssessmentLoading(true);
    setAssessmentError(null);
    setAssessmentResults(null);

    try {
      const response = await axios.post('/api/quality-assessment', {
        max_traces: 5,
        custom_guidelines: qualityGuidelines
      });

      setAssessmentResults(response.data);
      setAssessmentError(null);
    } catch (err) {
      console.error("Error running assessment:", err);
      setAssessmentError(err.response?.data?.detail || "Failed to run assessment");
    } finally {
      setAssessmentLoading(false);
    }
  };

  const getMlflowRunUrl = (runId) => {
    if (!mlflowConfig || !runId) return null;
    
    const { databricks_host, mlflow_experiment_id } = mlflowConfig;
    if (!databricks_host || !mlflow_experiment_id) return null;
    
    return `${databricks_host}/ml/experiments/${mlflow_experiment_id}/evaluation-runs?selectedRunUuid=${runId}`;
  };

  const loadMlflowConfig = async () => {
    try {
      const response = await axios.get('/api/env-check');
      if (response.data.environment_variables) {
        const env = response.data.environment_variables;
        setMlflowConfig({
          databricks_host: env.DATABRICKS_HOST,
          mlflow_experiment_id: env.MLFLOW_EXPERIMENT_ID
        });
      }
    } catch (err) {
      console.error("Error loading MLflow config:", err);
    }
  };

  return (
    <div className="App">
      <header className="App-header">
        <div className="header-content">
          <div className="logo-section">
            <img src="/gsk-logo.png" alt="GSK Logo" className="gsk-logo" />
          </div>
          <div className="title-section">
            <h1>Personalized Email Generator</h1>
            <p className="backend-status">{backendStatus}</p>
          </div>
          <button 
            className="sidebar-toggle"
            onClick={() => setSidebarOpen(!sidebarOpen)}
          >
            ☰
          </button>
        </div>
      </header>
      
      <div className="app-layout">
        {/* Sidebar */}
        <div className={`sidebar ${sidebarOpen ? 'open' : 'closed'}`}>
          <nav className="sidebar-nav">
            <div className="nav-section">
              <ul className="nav-list">
                <li>
                  <button 
                    className={`nav-item ${activeTab === 'demo-overview' ? 'active' : ''}`}
                    onClick={() => setActiveTab('demo-overview')}
                  >
                    <span className="nav-icon">▶️</span>
                    Demo Overview
                  </button>
                </li>
                <li>
                  <button 
                    className={`nav-item ${activeTab === 'observe-tracing' ? 'active' : ''}`}
                    onClick={() => setActiveTab('observe-tracing')}
                  >
                    <span className="nav-icon">🧪</span>
                    Observe with tracing
                  </button>
                </li>
                <li>
                  <button 
                    className={`nav-item ${activeTab === 'quality-metrics' ? 'active' : ''}`}
                    onClick={() => setActiveTab('quality-metrics')}
                  >
                    <span className="nav-icon">🎯</span>
                    Create quality metrics
                  </button>
                </li>
                <li>
                  <button 
                    className={`nav-item ${activeTab === 'find-fix-issues' ? 'active' : ''}`}
                    onClick={() => setActiveTab('find-fix-issues')}
                  >
                    <span className="nav-icon">📈</span>
                    Find & fix quality issues
                  </button>
                </li>
                <li>
                  <button 
                    className={`nav-item ${activeTab === 'production-monitoring' ? 'active' : ''}`}
                    onClick={() => setActiveTab('production-monitoring')}
                  >
                    <span className="nav-icon">⚡</span>
                    Production Monitoring
                  </button>
                </li>
                <li>
                  <button 
                    className={`nav-item ${activeTab === 'human-review' ? 'active' : ''}`}
                    onClick={() => setActiveTab('human-review')}
                  >
                    <span className="nav-icon">👥</span>
                    Human Review
                  </button>
                </li>
                <li>
                  <button 
                    className={`nav-item ${activeTab === 'business-kpis' ? 'active' : ''}`}
                    onClick={() => setActiveTab('business-kpis')}
                  >
                    <span className="nav-icon">📊</span>
                    Link to business KPIs
                  </button>
                </li>
              </ul>
            </div>
            
            <div className="nav-section">
              <ul className="nav-list">
                <li>
                  <a 
                    href={`${import.meta.env.VITE_DATABRICKS_HOST || 'https://adb-984752964297111.11.azuredatabricks.net'}/ml/experiments/${import.meta.env.VITE_MLFLOW_EXPERIMENT_ID || '2288977791043869'}/`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="nav-item gsk-experiment-box"
                  >
                    <span className="nav-icon gsk-icon-box">🔬</span>
                    MLflow Experiment
                    <span className="experiment-id">{import.meta.env.VITE_MLFLOW_EXPERIMENT_ID || '2288977791043869'}</span>
                  </a>
                </li>
              </ul>
            </div>
            
            <div className="nav-section">
              <h4>Get started on your own:</h4>
              <ul className="nav-list">
                <li>
                  <button 
                    className={`nav-item ${activeTab === 'mlflow-docs' ? 'active' : ''}`}
                    onClick={() => setActiveTab('mlflow-docs')}
                  >
                    <span className="nav-icon">📚</span>
                    MLflow Documentation
                  </button>
                </li>
                <li>
                  <button 
                    className={`nav-item ${activeTab === 'mlflow-website' ? 'active' : ''}`}
                    onClick={() => setActiveTab('mlflow-website')}
                  >
                    <span className="nav-icon">🌐</span>
                    MLflow Website
                  </button>
                </li>
                <li>
                  <button 
                    className={`nav-item ${activeTab === 'mlflow-quickstart' ? 'active' : ''}`}
                    onClick={() => setActiveTab('mlflow-quickstart')}
                  >
                    <span className="nav-icon">🔗</span>
                    MLflow Quickstart
                  </button>
                </li>
              </ul>
            </div>
          </nav>
        </div>
        
        {/* Main Content */}
        <div className={`main-content ${sidebarOpen ? 'with-sidebar' : 'full-width'}`}>
          <main>
            {activeTab === 'business-kpis' && (
              <div className="business-kpis-container">
                <div className="kpis-header">
                  <h1>Interactive Demo</h1>
                  <p>The example dashboard below shows you could link business KPIs to MLflow evaluation metrics to demonstrate the ROI of the email generation app.</p>
                </div>
                
                <div className="kpi-grid">
                  <div className="kpi-card">
                    <div className="kpi-icon">💰</div>
                    <div className="kpi-value">$2.4M</div>
                    <div className="kpi-label">Total Revenue</div>
                    <div className="kpi-change positive">+14.2% vs baseline</div>
                  </div>
                  <div className="kpi-card">
                    <div className="kpi-icon">📧</div>
                    <div className="kpi-value">24.3%</div>
                    <div className="kpi-label">Response Rate</div>
                    <div className="kpi-change positive">+2.1% vs baseline</div>
                  </div>
                  <div className="kpi-card">
                    <div className="kpi-icon">⏰</div>
                    <div className="kpi-value">847h</div>
                    <div className="kpi-label">Time Saved</div>
                    <div className="kpi-change positive">+23% efficiency</div>
                  </div>
                  <div className="kpi-card">
                    <div className="kpi-icon">📈</div>
                    <div className="kpi-value">340%</div>
                    <div className="kpi-label">ROI</div>
                    <div className="kpi-change positive">+45% vs baseline</div>
                  </div>
                </div>

                <div className="prompt-comparison-section">
                  <h2>Prompt Version ROI Comparison</h2>
                  <div className="prompt-comparison-grid">
                    <div className="prompt-card champion">
                      <div className="prompt-header">
                        <h3>Personalized Prompt</h3>
                        <span className="prompt-label champion">Champion</span>
                      </div>
                      <div className="prompt-metrics">
                        <div className="metric">
                          <span className="metric-label">Quality:</span>
                          <span className="metric-value">8.4/10</span>
                        </div>
                        <div className="metric">
                          <span className="metric-label">Response:</span>
                          <span className="metric-value">26.1%</span>
                        </div>
                        <div className="metric">
                          <span className="metric-label">ROI:</span>
                          <span className="metric-value">385%</span>
                        </div>
                      </div>
                    </div>
                    <div className="prompt-card control">
                      <div className="prompt-header">
                        <h3>Baseline Prompt</h3>
                        <span className="prompt-label control">Control</span>
                      </div>
                      <div className="prompt-metrics">
                        <div className="metric">
                          <span className="metric-label">Quality:</span>
                          <span className="metric-value">7.8/10</span>
                        </div>
                        <div className="metric">
                          <span className="metric-label">Response:</span>
                          <span className="metric-value">22.2%</span>
                        </div>
                        <div className="metric">
                          <span className="metric-label">ROI:</span>
                          <span className="metric-value">298%</span>
                        </div>
                      </div>
                    </div>
                    <div className="prompt-card challenger">
                      <div className="prompt-header">
                        <h3>Urgent Prompt</h3>
                        <span className="prompt-label challenger">Challenger</span>
                      </div>
                      <div className="prompt-metrics">
                        <div className="metric">
                          <span className="metric-label">Quality:</span>
                          <span className="metric-value">7.2/10</span>
                        </div>
                        <div className="metric">
                          <span className="metric-label">Response:</span>
                          <span className="metric-value">18.5%</span>
                        </div>
                        <div className="metric">
                          <span className="metric-label">ROI:</span>
                          <span className="metric-value">245%</span>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="business-impact-section">
                  <h2>Business Impact Over Time</h2>
                  <div className="impact-metrics">
                    <div className="impact-metric">
                      <span className="impact-label">$87K</span>
                      <span className="impact-subtitle">Avg Revenue/Week</span>
                    </div>
                    <div className="impact-metric">
                      <span className="impact-label">156</span>
                      <span className="impact-subtitle">Emails/Day</span>
                    </div>
                  </div>
                  <div className="progress-bars">
                    <div className="progress-item">
                      <div className="progress-label">Email Quality Score</div>
                      <div className="progress-bar">
                        <div className="progress-fill quality" style={{width: '84%'}}></div>
                      </div>
                      <span className="progress-value">8.4/10</span>
                    </div>
                    <div className="progress-item">
                      <div className="progress-label">Response Rate</div>
                      <div className="progress-bar">
                        <div className="progress-fill response" style={{width: '24.3%'}}></div>
                      </div>
                      <span className="progress-value">24.3%</span>
                    </div>
                    <div className="progress-item">
                      <div className="progress-label">Meeting Conversion</div>
                      <div className="progress-bar">
                        <div className="progress-fill conversion" style={{width: '68%'}}></div>
                      </div>
                      <span className="progress-value">68%</span>
                    </div>
                  </div>
                </div>

                <div className="success-summary-section">
                  <h2>Implementation Success Summary</h2>
                  <div className="success-grid">
                    <div className="success-card roi">
                      <div className="success-icon">📈</div>
                      <div className="success-value">340%</div>
                      <div className="success-label">Overall ROI</div>
                    </div>
                    <div className="success-card response">
                      <div className="success-icon">📧</div>
                      <div className="success-value">2.1%</div>
                      <div className="success-label">Response Rate Increase</div>
                    </div>
                    <div className="success-card time">
                      <div className="success-icon">⏰</div>
                      <div className="success-value">847</div>
                      <div className="success-label">Hours Saved</div>
                    </div>
                    <div className="success-card revenue">
                      <div className="success-icon">💰</div>
                      <div className="success-value">$2.4M</div>
                      <div className="success-label">Revenue Generated</div>
                    </div>
                  </div>
                </div>

                <div className="achievements-section">
                  <h2>Key Business Achievements</h2>
                  <ul className="achievements-list">
                    <li>14% increase in sales team productivity through automated email generation</li>
                    <li>2.1% improvement in email response rates using personalized prompts</li>
                    <li>$2.4M additional revenue attributed to GenAI-enhanced sales outreach</li>
                    <li>847 hours of manual work eliminated, allowing focus on high-value activities</li>
                    <li>95% statistical confidence in A/B test results validating improvements</li>
                    <li>Comprehensive MLflow tracking enabling continuous optimization</li>
                  </ul>
                </div>
              </div>
            )}
            
            {activeTab === 'quality-metrics' && (
              <div className="quality-metrics-container">
                <div className="guidelines-header">
                  <h1>Quality Assessment</h1>
                  <p>Customize guidelines and run assessments on recent production traces.</p>
                  <p>Guidelines allow you to customize Databricks' built-in judges to your use case.</p>
                </div>
                
                <div className="guidelines-section">
                  <div className="guidelines-header-row">
                    <h2>Custom Guidelines</h2>
                    <div className="guidelines-actions">
                      <button className="add-guideline-btn" onClick={handleAddGuideline}>+ Add Guideline</button>
                      <button 
                        className="run-assessment-btn" 
                        onClick={handleRunAssessment}
                        disabled={assessmentLoading}
                      >
                        {assessmentLoading ? 'Running Assessment...' : 'Run Assessment'}
                      </button>
                    </div>
                  </div>
                  
                  <div className="guidelines-list">
                    {Object.entries(qualityGuidelines).map(([guidelineName, guidelineContent]) => (
                      <div key={guidelineName} className="guideline-card">
                        <div className="guideline-header">
                          <div className="guideline-name-section">
                            <label>Guideline Name</label>
                            <input 
                              type="text" 
                              value={guidelineName} 
                              className="guideline-name-input"
                              onChange={(e) => {
                                const newName = e.target.value;
                                if (newName !== guidelineName) {
                                  const newGuidelines = { ...qualityGuidelines };
                                  delete newGuidelines[guidelineName];
                                  newGuidelines[newName] = guidelineContent;
                                  setQualityGuidelines(newGuidelines);
                                }
                              }}
                            />
                          </div>
                          <button 
                            className="delete-guideline-btn"
                            onClick={() => handleRemoveGuideline(guidelineName)}
                          >
                            🗑️
                          </button>
                        </div>
                        <div className="guideline-content">
                          <label>Guideline</label>
                          <textarea 
                            className="guideline-textarea" 
                            rows="12"
                            value={guidelineContent}
                            onChange={(e) => handleGuidelineUpdate(guidelineName, e.target.value)}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {assessmentError && (
                  <div className="assessment-error">
                    <h3>Assessment Error</h3>
                    <p>{assessmentError}</p>
                  </div>
                )}

                {assessmentResults && (
                  <div className="assessment-results">
                    <h3>Assessment Results</h3>
                    <div className="results-summary">
                      <div className="result-item">
                        <span className="result-label">Overall Score:</span>
                        <span className="result-value">{(assessmentResults.overall_score * 100).toFixed(1)}%</span>
                      </div>
                      <div className="result-item">
                        <span className="result-label">Total Evaluations:</span>
                        <span className="result-value">{assessmentResults.total_evaluations}</span>
                      </div>
                      <div className="result-item">
                        <span className="result-label">ID:</span>
                        <span className="result-value">
                          {assessmentResults.run_id ? (
                            getMlflowRunUrl(assessmentResults.run_id) ? (
                                                              <a 
                                  href={getMlflowRunUrl(assessmentResults.run_id)}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="run-id-link"
                                >
                                  {assessmentResults.run_id}
                                </a>
                            ) : (
                              <span className="run-id-text">{assessmentResults.run_id}</span>
                            )
                          ) : (
                            <span className="run-id-text">N/A</span>
                          )}
                        </span>
                      </div>
                    </div>
                    
                    <div className="metrics-breakdown">
                      <h4>Metrics Breakdown</h4>
                      {Object.entries(assessmentResults.metrics).map(([metricName, metricData]) => (
                        <div key={metricName} className="metric-item">
                          <span className="metric-name">{metricName}:</span>
                          <span className="metric-score">{(metricData.score * 100).toFixed(1)}%</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
            
            {activeTab === 'demo-overview' && (
              <div className="panels-container">
                {/* Left Panel - Input */}
                <div className="panel panel-left">
                  <div className="form-section">
                    <div className="section-header">
                      <h2>Customer Information</h2>
                    </div>
                   
                    {/* Company Selector */}
                    <div className="form-group">
                      <label htmlFor="company-select">Select Company</label>
                      <div className="typeahead-container">
                        <input
                          id="company-select"
                          type="text"
                          value={searchQuery}
                          onChange={handleSearchChange}
                          onFocus={() => setShowDropdown(true)}
                          onBlur={() => setTimeout(() => setShowDropdown(false), 200)}
                          className="company-select"
                          placeholder="Type to search companies..."
                          disabled={loadingCompanies}
                        />
                        {showDropdown && filteredCompanies.length > 0 && (
                          <div className="dropdown">
                            {filteredCompanies.map((company) => (
                              <div
                                key={company.name}
                                className={`dropdown-item ${selectedCompany === company.name ? 'selected' : ''}`}
                                onMouseDown={() => handleCompanySelect(company.name)}
                              >
                                {company.name}
                              </div>
                            ))}
                          </div>
                        )}
                        {showDropdown && searchQuery && filteredCompanies.length === 0 && (
                          <div className="dropdown">
                            <div className="dropdown-item no-results">
                              No companies found matching "{searchQuery}"
                            </div>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* User Instructions - Moved here */}
                    {customerData && (
                      <div className="instructions-section">
                        <div className="form-section-header">
                          <h3>Email Instructions</h3>
                        </div>
                        <div className="form-group">
                          <label htmlFor="user-instructions">
                            Add any specific instructions or context for the email
                          </label>
                          <textarea
                            id="user-instructions"
                            value={userInstructions}
                            onChange={(e) => setUserInstructions(e.target.value)}
                            placeholder="E.g., Mention the upcoming product launch, emphasize our new pricing model, schedule a demo for next week..."
                            rows={4}
                            className="instructions-textarea"
                          />
                        </div>
                      </div>
                    )}

                    {/* Generate Email Button */}
                    {customerData && (
                      <div className="generate-button-section">
                        <button 
                          onClick={handleGenerateEmail} 
                          disabled={loading || isStreaming}
                          className="generate-button"
                        >
                          {loading || isStreaming ? 'Generating 🚀' : 'Generate Email 👉'}
                        </button>
                      </div>
                    )}

                    {/* Customer Data Form */}
                    {customerData && (
                      <>
                        <div className="customer-form">
                          {/* Account Information */}
                          <div className="form-section-header">
                            <h3>Account Details</h3>
                          </div>
                          
                          <div className="form-row">
                            <div className="form-group">
                              <label>Industry</label>
                              <select
                                value={customerData.account.industry}
                                onChange={(e) => updateNestedField('account.industry', e.target.value)}
                              >
                                <option value="">Select Industry</option>
                                <option value="Aerospace">Aerospace</option>
                                <option value="Agriculture">Agriculture</option>
                                <option value="Architecture">Architecture</option>
                                <option value="Automotive">Automotive</option>
                                <option value="Banking">Banking</option>
                                <option value="Biotechnology">Biotechnology</option>
                                <option value="Construction">Construction</option>
                                <option value="Consulting">Consulting</option>
                                <option value="E-commerce">E-commerce</option>
                                <option value="Education">Education</option>
                                <option value="Energy & Utilities">Energy & Utilities</option>
                                <option value="Engineering">Engineering</option>
                                <option value="Entertainment & Media">Entertainment & Media</option>
                                <option value="Environmental Services">Environmental Services</option>
                                <option value="Fashion">Fashion</option>
                                <option value="Food & Beverage">Food & Beverage</option>
                                <option value="Government">Government</option>
                                <option value="Healthcare">Healthcare</option>
                                <option value="Hospitality">Hospitality</option>
                                <option value="Insurance">Insurance</option>
                                <option value="Legal Services">Legal Services</option>
                                <option value="Manufacturing">Manufacturing</option>
                                <option value="Non-profit">Non-profit</option>
                                <option value="Pharmaceuticals">Pharmaceuticals</option>
                                <option value="Real Estate">Real Estate</option>
                                <option value="Retail">Retail</option>
                                <option value="Software">Software</option>
                                <option value="Sports & Recreation">Sports & Recreation</option>
                                <option value="Technology">Technology</option>
                                <option value="Transportation & Logistics">Transportation & Logistics</option>
                              </select>
                            </div>
                            <div className="form-group">
                              <label>Size</label>
                              <select
                                value={customerData.account.size}
                                onChange={(e) => updateNestedField('account.size', e.target.value)}
                              >
                                <option value="">Select Size</option>
                                <optgroup label="Simple Categories">
                                  <option value="Small Business">Small Business</option>
                                  <option value="Mid-market">Mid-market</option>
                                  <option value="Enterprise">Enterprise</option>
                                </optgroup>
                                <optgroup label="Detailed Categories">
                                  <option value="Small Business (10-50 employees)">Small Business (10-50 employees)</option>
                                  <option value="Small Business (51-100 employees)">Small Business (51-100 employees)</option>
                                  <option value="Mid-market (101-500 employees)">Mid-market (101-500 employees)</option>
                                  <option value="Mid-market (501-1000 employees)">Mid-market (501-1000 employees)</option>
                                  <option value="Enterprise (1001-5000 employees)">Enterprise (1001-5000 employees)</option>
                                  <option value="Enterprise (5000+ employees)">Enterprise (5000+ employees)</option>
                                </optgroup>
                              </select>
                            </div>
                          </div>

                          {/* Main Contact */}
                          <div className="form-section-header">
                            <h3>Main Contact</h3>
                          </div>
                          
                          <div className="form-row">
                            <div className="form-group">
                              <label>Name</label>
                              <input
                                type="text"
                                value={customerData.account.main_contact.name}
                                onChange={(e) => updateNestedField('account.main_contact.name', e.target.value)}
                              />
                            </div>
                            <div className="form-group">
                              <label>Title</label>
                              <input
                                type="text"
                                value={customerData.account.main_contact.title}
                                onChange={(e) => updateNestedField('account.main_contact.title', e.target.value)}
                              />
                            </div>
                            <div className="form-group">
                              <label>Email</label>
                              <input
                                type="email"
                                value={customerData.account.main_contact.email}
                                onChange={(e) => updateNestedField('account.main_contact.email', e.target.value)}
                              />
                            </div>
                          </div>

                          {/* Relationship Status */}
                          <div className="form-section-header">
                            <h3>Relationship Status</h3>
                          </div>
                          
                          <div className="form-row">
                            <div className="form-group">
                              <label>Customer Since</label>
                              <input
                                type="date"
                                value={customerData.account.relationship.customer_since}
                                onChange={(e) => updateNestedField('account.relationship.customer_since', e.target.value)}
                              />
                            </div>
                            <div className="form-group">
                              <label>Deal Stage</label>
                              <select
                                value={customerData.account.relationship.deal_stage}
                                onChange={(e) => updateNestedField('account.relationship.deal_stage', e.target.value)}
                              >
                                <option value="New Customer">New Customer</option>
                                <option value="Onboarding">Onboarding</option>
                                <option value="Implementation">Implementation</option>
                                <option value="Growth">Growth</option>
                                <option value="Mature">Mature</option>
                                <option value="Expansion">Expansion</option>
                                <option value="At Risk">At Risk</option>
                              </select>
                            </div>
                            <div className="form-group">
                              <label>Account Health</label>
                              <select
                                value={customerData.account.relationship.account_health}
                                onChange={(e) => updateNestedField('account.relationship.account_health', e.target.value)}
                                className={`health-select health-${customerData.account.relationship.account_health.toLowerCase()}`}
                              >
                                <option value="Excellent">Excellent</option>
                                <option value="Good">Good</option>
                                <option value="Fair">Fair</option>
                                <option value="Poor">Poor</option>
                              </select>
                            </div>
                          </div>

                          {/* Recent Activity Summary */}
                          <div className="form-section-header">
                            <h3>Recent Activity</h3>
                          </div>
                          
                          <div className="activity-summary">
                            <div className="stat-card">
                              <span className="stat-label">Active Users</span>
                              <span className="stat-value">{customerData.recent_activity.product_usage.active_users}</span>
                              <span className="stat-change">{customerData.recent_activity.product_usage.active_users_change}</span>
                            </div>
                            <div className="stat-card">
                              <span className="stat-label">Last Meeting</span>
                              <span className="stat-value">{customerData.recent_activity.meetings[0]?.date || 'N/A'}</span>
                              <span className="stat-subtitle">{customerData.recent_activity.meetings[0]?.type || ''}</span>
                            </div>
                            <div className="stat-card">
                              <span className="stat-label">Open Tickets</span>
                              <span className="stat-value">
                                {customerData.recent_activity.support_tickets.filter(t => t.status.includes('Open')).length}
                              </span>
                              <span className="stat-subtitle">Support Issues</span>
                            </div>
                          </div>

                          {/* Meetings Details */}
                          {customerData.recent_activity.meetings.length > 0 && (
                            <div className="activity-details">
                              <h4>Recent Meetings</h4>
                              {customerData.recent_activity.meetings.map((meeting, idx) => (
                                <div key={idx} className="meeting-card">
                                  <div className="meeting-header">
                                    <span className="meeting-type">{meeting.type}</span>
                                    <span className="meeting-date">{meeting.date}</span>
                                  </div>
                                  <p className="meeting-summary">{meeting.summary}</p>
                                  {meeting.action_items && meeting.action_items.length > 0 && (
                                    <div className="action-items">
                                      <strong>Action Items:</strong>
                                      <ul>
                                        {meeting.action_items.map((item, itemIdx) => (
                                          <li key={itemIdx}>{item}</li>
                                        ))}
                                      </ul>
                                    </div>
                                  )}
                                </div>
                              ))}
                            </div>
                          )}

                          {/* Product Usage */}
                          <div className="activity-details">
                            <h4>Product Usage Insights</h4>
                            <div className="usage-grid">
                              <div className="usage-section">
                                <h5>Most Used Features</h5>
                                <ul className="feature-list">
                                  {customerData.recent_activity.product_usage.most_used_features.map((feature, idx) => (
                                    <li key={idx} className="feature-item used">{feature}</li>
                                  ))}
                                </ul>
                              </div>
                              <div className="usage-section">
                                <h5>Least Used Features</h5>
                                <ul className="feature-list">
                                  {customerData.recent_activity.product_usage.least_used_features.map((feature, idx) => (
                                    <li key={idx} className="feature-item unused">{feature}</li>
                                  ))}
                                </ul>
                              </div>
                            </div>
                            {customerData.recent_activity.product_usage.potential_opportunity && (
                              <div className="opportunity-box">
                                <strong>Opportunity:</strong> {customerData.recent_activity.product_usage.potential_opportunity}
                              </div>
                            )}
                          </div>

                          {/* Support Tickets */}
                          {customerData.recent_activity.support_tickets.length > 0 && (
                            <div className="activity-details">
                              <h4>Support Tickets</h4>
                              <div className="tickets-grid">
                                {customerData.recent_activity.support_tickets.map((ticket, idx) => (
                                  <div key={idx} className={`ticket-card ${ticket.status.includes('Open') ? 'open' : 'resolved'}`}>
                                    <div className="ticket-header">
                                      <span className="ticket-id">{ticket.id}</span>
                                      <span className={`ticket-status ${ticket.status.toLowerCase().replace(/\s+/g, '-')}`}>
                                        {ticket.status}
                                      </span>
                                    </div>
                                    <p className="ticket-issue">{ticket.issue}</p>
                                    {ticket.priority && (
                                      <span className={`ticket-priority priority-${ticket.priority.toLowerCase()}`}>
                                        Priority: {ticket.priority}
                                      </span>
                                    )}
                                    {ticket.resolution && (
                                      <p className="ticket-resolution">
                                        <strong>Resolution:</strong> {ticket.resolution}
                                      </p>
                                    )}
                                  </div>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Sales Rep */}
                          <div className="form-section-header">
                            <h3>Sales Representative</h3>
                          </div>
                          
                          <div className="form-row">
                            <div className="form-group">
                              <label>Name</label>
                              <input
                                type="text"
                                value={customerData.sales_rep.name}
                                onChange={(e) => updateNestedField('sales_rep.name', e.target.value)}
                              />
                            </div>
                            <div className="form-group">
                              <label>Title</label>
                              <input
                                type="text"
                                value={customerData.sales_rep.title}
                                onChange={(e) => updateNestedField('sales_rep.title', e.target.value)}
                              />
                            </div>
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                </div>

                {/* Right Panel - Output */}
                <div className="panel panel-right">
                  <div className="output-section">
                    <h2>Generated Email</h2>
                    
                    {!generatedEmail && !loading && !isStreaming && !streamingContent && !streamingEmail.subject_line && !streamingEmail.body && (
                      <div className="empty-state">
                        <p>Select a company and click "Generate Email" to see the personalized email here.</p>
                      </div>
                    )}
                    
                    {(loading || isStreaming || (streamingEmail.subject_line || streamingEmail.body)) && !generatedEmail && (
                      <div className="loading-state">
                        {(loading || isStreaming) && <p>Generating personalized email...</p>}
                        {(streamingEmail.subject_line || streamingEmail.body) && (
                          <div className="streaming-preview">
                            {streamingEmail.subject_line && (
                              <div className="streaming-subject">
                                <h3>Subject: {streamingEmail.subject_line}</h3>
                              </div>
                            )}
                            {streamingEmail.body && (
                              <div className="email-body streaming markdown-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(streamingEmail.body) }} />
                            )}
                          </div>
                        )}
                      </div>
                    )}
                    
                    {error && (
                      <div className="error-message">
                        <h3>Error</h3>
                        <pre>{error}</pre>
                      </div>
                    )}

                    {generatedEmail && !loading && !isStreaming && (
                      <div className="email-output">
                        <div className="email-content">
                          <h3>Subject: {generatedEmail.subject_line}</h3>
                          <div className="email-body markdown-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(generatedEmail.body) }} />
                        </div>
                        
                        {/* Enhanced Feedback Widget */}
                        <div className="feedback-widget">
                          <div className="feedback-header">
                            <h4>How was this email?</h4>
                            <p>Your feedback helps improve the email generation quality</p>
                            {currentTraceId && feedbackSubmitted && (
                              <div className="trace-view-section">
                                <a 
                                  href={`${import.meta.env.VITE_DATABRICKS_HOST || 'https://adb-984752964297111.11.azuredatabricks.net'}/ml/experiments/${import.meta.env.VITE_MLFLOW_EXPERIMENT_ID || '2288977791043869'}/traces?selectedEvaluationId=${currentTraceId}`}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="view-trace-btn"
                                  title="View trace in MLflow"
                                >
                                  <span className="trace-icon">🔍</span>
                                  View Trace in MLflow
                                </a>
                              </div>
                            )}
                          </div>
                          
                          <div className="feedback-buttons">
                            <button 
                              className={`feedback-btn thumbs-up ${feedbackRating === 'up' ? 'active' : ''}`}
                              onClick={() => handleFeedbackRating('up')}
                              title="Good email"
                            >
                              <span className="feedback-icon">👍</span>
                              <span className="feedback-label">Good</span>
                            </button>
                            <button 
                              className={`feedback-btn thumbs-down ${feedbackRating === 'down' ? 'active' : ''}`}
                              onClick={() => handleFeedbackRating('down')}
                              title="Needs improvement"
                            >
                              <span className="feedback-icon">👎</span>
                              <span className="feedback-label">Needs Work</span>
                            </button>
                          </div>
                          
                          {feedbackRating && (
                            <div className="feedback-comment-section">
                              <label htmlFor="feedback-comment">Additional comments (optional):</label>
                              <textarea
                                id="feedback-comment"
                                className="feedback-comment"
                                placeholder="Share specific feedback about the email quality, tone, content, or suggestions for improvement..."
                                value={feedbackComment}
                                onChange={(e) => setFeedbackComment(e.target.value)}
                                rows={4}
                              />
                              <div className="feedback-submit-section">
                                <button 
                                  className="feedback-submit-btn"
                                  onClick={handleFeedbackSubmit}
                                  disabled={feedbackSubmitted || !currentTraceId}
                                >
                                  {feedbackSubmitted ? (
                                    <>
                                      <span className="success-icon">✓</span>
                                      Thank you for your feedback!
                                    </>
                                  ) : (
                                    <>
                                      <span className="submit-icon">📤</span>
                                      Submit Feedback
                                    </>
                                  )}
                                </button>
                                {feedbackSubmitted && (
                                  <p className="feedback-success-message">
                                    Your feedback has been recorded and will help improve future email generations.
                                  </p>
                                )}
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
            
            {!['business-kpis', 'quality-metrics', 'demo-overview'].includes(activeTab) && (
              <div className="default-content">
                <div className="default-header">
                  <h1>MLflow Demo</h1>
                  <p>Select a tab from the sidebar to explore different aspects of the MLflow 3.0 GenAI demo.</p>
                </div>
              </div>
            )}
          </main>
        </div>
      </div>
    </div>
  );
}

export default App; 