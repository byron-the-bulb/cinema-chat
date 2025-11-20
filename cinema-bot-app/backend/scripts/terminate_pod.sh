#!/bin/bash

# Define the config file path (adjust if needed)
CONFIG_FILE="/root/.runpodctl/config"

# Check if the config file exists; if not, configure it
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Config file not found, configuring runpodctl..."
    
    # Use the API key from an environment variable (e.g., RUNPOD_API_KEY)
    if [ -z "$RUNPOD_API_KEY" ]; then
        echo "Error: RUNPOD_API_KEY environment variable is not set."
        exit 1
    fi
    
    runpodctl config --apiKey="$RUNPOD_API_KEY"
    if [ $? -eq 0 ]; then
        echo "runpodctl configured successfully."
    else
        echo "Failed to configure runpodctl."
        exit 1
    fi
else
    echo "Config file found, proceeding..."
fi

# Stop the pod using the pod ID from an environment variable (e.g., RUNPOD_POD_ID)
if [ -z "$RUNPOD_POD_ID" ]; then
    echo "Error: RUNPOD_POD_ID environment variable is not set."
    exit 1
fi

# Dump container logs before removing the pod
echo "Dumping logs for container $RUNPOD_POD_ID..."

# Try multiple methods to get logs (in order of preference)
if [ -f "/app/logs/cinema_bot.log" ]; then
    # Check for our newly created log file first (from entrypoint.sh) and show its size
    echo "Found log file at /app/logs/cinema_bot.log. Size: $(wc -c < /app/logs/cinema_bot.log) bytes."
    cp /app/logs/cinema_bot.log container_logs.txt
elif [ -f "/var/log/cinema-bot.log" ]; then
    # If cinema-bot logs to a specific file
    echo "Found log file at /var/log/cinema-bot.log. Size: $(wc -c < /var/log/cinema-bot.log) bytes."
    cp /var/log/cinema-bot.log container_logs.txt
elif [ -d "/proc/1/fd" ]; then
    # Try to get stdout/stderr from the process filesystem
    echo "Using process stdout/stderr capture method"
    cat /proc/1/fd/1 > container_logs.txt 2>/dev/null
    cat /proc/1/fd/2 >> container_logs.txt 2>/dev/null
elif command -v journalctl >/dev/null 2>&1; then
    # If systemd is being used
    echo "Using journalctl to capture logs"
    journalctl -u cinema-bot --no-pager > container_logs.txt 2>/dev/null || journalctl --no-pager > container_logs.txt
elif command -v docker >/dev/null 2>&1; then
    # Try docker logs if command is available
    echo "Using docker logs command"
    docker logs "$RUNPOD_POD_ID" > container_logs.txt 2>/dev/null
else
    # Fallback to any potential log files
    echo "Trying to find log files in common locations"
    find /var/log -type f -name "*.log" -exec cat {} \; > container_logs.txt 2>/dev/null
    # Also capture application output if running in standard locations
    if [ -d "/app" ]; then
        find /app -name "*.log" -exec cat {} \; >> container_logs.txt 2>/dev/null
    fi
    if [ -d "/root" ]; then
        find /root -name "*.log" -exec cat {} \; >> container_logs.txt 2>/dev/null
    fi
fi

# Check if we got any logs
if [ -s container_logs.txt ]; then
    # Display container_logs.txt size
    echo "Logs captured to container_logs.txt. Size: $(wc -c < container_logs.txt) bytes."
    # Upload logs to CloudWatch (requires AWS credentials)
    if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
        echo "AWS credentials not set. Skipping CloudWatch upload."
    else
        # Set default values if not specified
        AWS_REGION=${AWS_REGION:-"us-east-1"}
        CLOUDWATCH_LOG_GROUP=${CLOUDWATCH_LOG_GROUP:-"/cinema-chat-bot"}
        #use LOG_STREAM if it is set, if not use IDENTIFIER
        if [ -z "$LOG_STREAM" ]; then
            LOG_STREAM="${IDENTIFIER}-OnPodExit-$(date +%s)"
        fi
        
        echo "Uploading logs to CloudWatch log group: $CLOUDWATCH_LOG_GROUP, stream: $LOG_STREAM"
        
        # Create log group if it doesn't exist
        aws logs create-log-group --log-group-name "$CLOUDWATCH_LOG_GROUP" --region "$AWS_REGION" 2>/dev/null || true
        
        # Create log stream if it doesn't exist
        aws logs create-log-stream --log-group-name "$CLOUDWATCH_LOG_GROUP" --log-stream-name "$LOG_STREAM" --region "$AWS_REGION" 2>/dev/null || true
        
        # Split the log file into chunks (CloudWatch has a 1MB event size limit)
        # First, compress the logs to save space
        gzip -c container_logs.txt > container_logs.txt.gz
        CHUNK_SIZE=800000  # ~800KB to stay under CloudWatch's 1MB limit
        
        # Ensure we have the split utility
        if ! command -v split &> /dev/null; then
            echo "Split utility not found, uploading compressed log as a single batch"
            
            # Upload the compressed log file directly
            LOG_TIMESTAMP=$(date +%s%3N)  # Milliseconds since epoch
            aws logs put-log-events \
                --log-group-name "$CLOUDWATCH_LOG_GROUP" \
                --log-stream-name "$LOG_STREAM" \
                --log-events "timestamp=$LOG_TIMESTAMP,message=\"$(base64 container_logs.txt.gz)\"" \
                --region "$AWS_REGION"
                
            if [ $? -eq 0 ]; then
                echo "Compressed logs uploaded to CloudWatch successfully."
            else
                echo "Failed to upload compressed logs to CloudWatch."
            fi
        else
            # Split the file and upload chunks
            split -b $CHUNK_SIZE container_logs.txt container_logs_chunk_
            echo "Split logs into $(ls container_logs_chunk_* | wc -l) chunks for CloudWatch upload"
            
            # Track sequence token for consecutive uploads
            SEQUENCE_TOKEN=""
            
            for CHUNK_FILE in container_logs_chunk_*; do
                # Prepare the log events
                LOG_TIMESTAMP=$(date +%s%3N)  # Milliseconds since epoch
                
                if [ -z "$SEQUENCE_TOKEN" ]; then
                    # First upload doesn't need a sequence token
                    RESPONSE=$(aws logs put-log-events \
                        --log-group-name "$CLOUDWATCH_LOG_GROUP" \
                        --log-stream-name "$LOG_STREAM" \
                        --log-events "timestamp=$LOG_TIMESTAMP,message=\"$(cat $CHUNK_FILE)\"" \
                        --region "$AWS_REGION" 2>&1)
                else
                    # Subsequent uploads need the sequence token
                    RESPONSE=$(aws logs put-log-events \
                        --log-group-name "$CLOUDWATCH_LOG_GROUP" \
                        --log-stream-name "$LOG_STREAM" \
                        --log-events "timestamp=$LOG_TIMESTAMP,message=\"$(cat $CHUNK_FILE)\"" \
                        --sequence-token "$SEQUENCE_TOKEN" \
                        --region "$AWS_REGION" 2>&1)
                fi
                
                # Check if we need to retry with a different sequence token
                if echo "$RESPONSE" | grep -q "The given sequenceToken is invalid"; then
                    # Extract the correct sequence token from the error message
                    NEW_TOKEN=$(echo "$RESPONSE" | grep -o "sequenceToken is: [^ ]*" | cut -d' ' -f3)
                    if [ ! -z "$NEW_TOKEN" ]; then
                        echo "Retrying with correct sequence token: $NEW_TOKEN"
                        SEQUENCE_TOKEN="$NEW_TOKEN"
                        
                        # Retry with the correct sequence token
                        RESPONSE=$(aws logs put-log-events \
                            --log-group-name "$CLOUDWATCH_LOG_GROUP" \
                            --log-stream-name "$LOG_STREAM" \
                            --log-events "timestamp=$LOG_TIMESTAMP,message=\"$(cat $CHUNK_FILE)\"" \
                            --sequence-token "$SEQUENCE_TOKEN" \
                            --region "$AWS_REGION" 2>&1)
                    fi
                fi
                
                # Extract next sequence token for subsequent uploads
                SEQUENCE_TOKEN=$(echo "$RESPONSE" | grep -o '"nextSequenceToken": "[^"]*"' | cut -d'"' -f4)
                
                echo "Uploaded chunk $CHUNK_FILE to CloudWatch"
            done
            
            echo "All log chunks uploaded to CloudWatch: $CLOUDWATCH_LOG_GROUP/$LOG_STREAM"
            # Clean up the chunk files
            rm container_logs_chunk_*
        fi
        
        # Clean up
        rm container_logs.txt container_logs.txt.gz
    fi
else
    echo "Failed to dump container logs."
fi

echo "Waiting 60 seconds before removing the pod..."
sleep 60

runpodctl remove pod "$RUNPOD_POD_ID"
if [ $? -eq 0 ]; then
    echo "Pod $RUNPOD_POD_ID removed successfully."
else
    echo "Failed to remove pod $RUNPOD_POD_ID."
    exit 1
fi
