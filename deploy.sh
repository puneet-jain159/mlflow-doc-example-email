#!/bin/bash

# Source .env file if it exists
if [[ -f ".env" ]]; then
    # Export all variables from .env file
    set -a
    source .env
    set +a
else
    echo "Error: .env file not found. Please create one with required variables."
    exit 1
fi

# Check if required variables are set
if [[ -z "$LAKEHOUSE_APP_NAME" || -z "$APP_FOLDER_IN_WORKSPACE" ]]; then
    echo "Error: Required environment variables LAKEHOUSE_APP_NAME and APP_FOLDER_IN_WORKSPACE are not set in .env file."
    exit 1
fi

# Function to update app.yaml with environment variables from .env
update_app_yaml() {
    local env_file=".env"
    local app_yaml="databricks-app/app.yaml"
    
    # Check if .env file exists
    if [[ ! -f "$env_file" ]]; then
        echo "Warning: .env file not found. Using existing app.yaml without modifications."
        return
    fi
    
    echo "Reading environment variables from $env_file..."
    
    # Create temporary files to store variables
    local temp_vars=$(mktemp)
    local temp_yaml=$(mktemp)
    
    # First pass: clean and store all variables
    while IFS='=' read -r key value || [[ -n "$key" ]]; do
        # Skip empty lines and comments
        [[ -z "$key" || "$key" =~ ^[[:space:]]*# ]] && continue
        
        # Remove any surrounding quotes and whitespace
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)
        
        # Remove quotes if they exist
        if [[ "$value" =~ ^[\"\'].*[\"\']$ ]]; then
            value="${value:1:-1}"
        fi
        
        # Store in temporary file
        echo "$key=$value" >> "$temp_vars"
        
    done < "$env_file"
    
    # Function to resolve variable references
    resolve_var_refs() {
        local value="$1"
        local resolved="$value"
        
        # Replace ${VAR_NAME} with actual values from temp_vars file
        while [[ "$resolved" =~ \$\{([^}]+)\} ]]; do
            local var_name="${BASH_REMATCH[1]}"
            local var_value=""
            
            # Look up the variable in our temp file
            if grep -q "^$var_name=" "$temp_vars"; then
                var_value=$(grep "^$var_name=" "$temp_vars" | head -1 | cut -d'=' -f2-)
            fi
            
            if [[ -n "$var_value" ]]; then
                resolved="${resolved/\$\{$var_name\}/$var_value}"
            else
                echo "Warning: Variable reference \${$var_name} not found in .env file"
                break
            fi
        done
        echo "$resolved"
    }
    
    # Write the command section
    cat > "$temp_yaml" << 'EOF'
command: [
  "uvicorn",
  "app:app"
]

env:
EOF
    
    # Second pass: process variables and write to YAML
    while IFS='=' read -r key value; do
        [[ -z "$key" ]] && continue
        
        # Skip Databricks authentication variables (used for deployment, not runtime)
        if [[ "$key" == "DATABRICKS_TOKEN" || "$key" == "DATABRICKS_HOST" ]]; then
            echo "Skipping $key (deployment-only variable)"
            continue
        fi
        
        # Resolve any variable references in the value
        local resolved_value
        resolved_value=$(resolve_var_refs "$value")
        
        # Add to YAML format
        echo "  - name: '$key'" >> "$temp_yaml"
        echo "    value: '$resolved_value'" >> "$temp_yaml"
        
    done < "$temp_vars"
    
    # Add GIT_COMMIT_HASH if it's set in the environment
    if [[ -n "$GIT_COMMIT_HASH" ]]; then
        echo "  - name: 'GIT_COMMIT_HASH'" >> "$temp_yaml"
        echo "    value: '$GIT_COMMIT_HASH'" >> "$temp_yaml"
        echo "Added GIT_COMMIT_HASH to app.yaml: $GIT_COMMIT_HASH"
    fi
    
    # Replace the original app.yaml
    mv "$temp_yaml" "$app_yaml"
    rm -f "$temp_vars"
    echo "Updated $app_yaml with environment variables from $env_file"
}

# Set GIT_COMMIT_HASH environment variable using deterministic git logic
set_git_commit_hash() {
    # Check if GIT_COMMIT_HASH is already set
    if [[ -n "$GIT_COMMIT_HASH" ]]; then
        echo "GIT_COMMIT_HASH already set: $GIT_COMMIT_HASH"
        return
    fi
    
    echo "Determining git commit hash..."
    
    # Get HEAD commit hash
    if ! head_hash=$(git rev-parse HEAD 2>/dev/null); then
        echo "Warning: Failed to get git HEAD hash"
        return
    fi
    
    # Check if repository is dirty
    if git_status_output=$(git status --porcelain 2>/dev/null) && [[ -n "$git_status_output" ]]; then
        # Repository has uncommitted changes, create deterministic hash
        echo "Repository is dirty, creating deterministic hash..."
        
        if diff_content=$(git diff HEAD 2>/dev/null); then
            # Create deterministic hash from HEAD + diff
            content_to_hash="$head_hash"$'\n'"$diff_content"
            changes_hash=$(echo -n "$content_to_hash" | shasum -a 256 | cut -d' ' -f1)
            
            # Combine HEAD hash (first 32 chars) + dirty indicator + changes hash (first 8 chars)
            export GIT_COMMIT_HASH="${head_hash:0:32}-dirty-${changes_hash:0:8}"
            echo "Set GIT_COMMIT_HASH (dirty): $GIT_COMMIT_HASH"
        else
            echo "Warning: Failed to get git diff, using HEAD only"
            export GIT_COMMIT_HASH="$head_hash"
            echo "Set GIT_COMMIT_HASH (fallback): $GIT_COMMIT_HASH"
        fi
    else
        # Repository is clean, use HEAD hash
        echo "Repository is clean, using HEAD hash..."
        export GIT_COMMIT_HASH="$head_hash"
        echo "Set GIT_COMMIT_HASH (clean): $GIT_COMMIT_HASH"
    fi
}

# Set the git commit hash
set_git_commit_hash

# Update app.yaml with environment variables
update_app_yaml

# Frontend build and import
(
  cd frontend
  
  # Extract VITE variables from app.yaml
  echo "Extracting VITE variables from app.yaml..."
  if [[ -f "../databricks-app/app.yaml" ]]; then
    # Parse YAML to extract VITE variables
    export VITE_DATABRICKS_HOST=$(grep -A1 "name: 'VITE_DATABRICKS_HOST'" ../databricks-app/app.yaml | grep "value:" | sed "s/.*value: '\(.*\)'/\1/")
    export VITE_MLFLOW_EXPERIMENT_ID=$(grep -A1 "name: 'VITE_MLFLOW_EXPERIMENT_ID'" ../databricks-app/app.yaml | grep "value:" | sed "s/.*value: '\(.*\)'/\1/")
    
    if [[ -n "$VITE_DATABRICKS_HOST" ]]; then
      echo "Exported VITE_DATABRICKS_HOST=$VITE_DATABRICKS_HOST"
    fi
    if [[ -n "$VITE_MLFLOW_EXPERIMENT_ID" ]]; then
      echo "Exported VITE_MLFLOW_EXPERIMENT_ID=$VITE_MLFLOW_EXPERIMENT_ID"
    fi
  else
    echo "Warning: app.yaml not found, VITE variables will not be set"
  fi
  
  npm run build:ignore-types
  # Copy the built files to databricks-app/static
  rm -rf ../databricks-app/static
  cp -r dist ../databricks-app/static
  echo "Frontend build complete and copied to databricks-app/static"
) &

# Backend packaging and workspace import
(
  # Freeze uv environment to requirements.txt
  echo "Freezing uv environment to requirements.txt..."
  uv pip compile pyproject.toml > databricks-app/requirements.txt
  echo "Requirements exported to databricks-app/requirements.txt"
  
  # Delete existing workspace path if it exists
  echo "Cleaning up existing workspace path..."
  /opt/homebrew/bin/databricks workspace delete "$APP_FOLDER_IN_WORKSPACE" --recursive || true
  
  # Import the directory to the workspace using import-dir
  echo "Importing application directory to workspace..."
  /opt/homebrew/bin/databricks workspace import-dir databricks-app "$APP_FOLDER_IN_WORKSPACE" --overwrite
) &

# Wait for both background processes to finish
wait

# Deploy the application using the newer CLI directly
echo "Deploying application from workspace path..."
/opt/homebrew/bin/databricks apps deploy "$LAKEHOUSE_APP_NAME" --source-code-path="$APP_FOLDER_IN_WORKSPACE"

# Print the app page URL -- put your workspace name in the below URL.
echo "Deployed!"
