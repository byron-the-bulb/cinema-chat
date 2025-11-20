"""
AWS CloudWatch logging integration module for Cinema Chat Voice Bot.

This module provides a custom CloudWatch sink for loguru that sends logs
directly to AWS CloudWatch Logs service.
"""

import os
import time
import boto3
from loguru import logger


class CloudWatchSink:
    """
    Custom sink for loguru that sends logs to AWS CloudWatch.
    
    This implementation directly uses boto3 to interact with CloudWatch Logs
    rather than relying on a third-party package.
    """
    
    def __init__(self, session, log_group, stream_name):
        """
        Initialize the CloudWatch sink with AWS session and log configuration.
        
        Args:
            session: boto3 Session object with AWS credentials
            log_group: Name of the CloudWatch log group
            stream_name: Name of the CloudWatch log stream
        """
        self.client = session.client('logs')
        self.log_group = log_group
        self.stream_name = stream_name
        self.sequence_token = None
        self.enabled = True  # Flag to track if sink is operational
        self.init_done = False  # Flag to avoid repeated error messages
        
        # Create log group if it doesn't exist
        try:
            self.client.create_log_group(logGroupName=log_group)
        except self.client.exceptions.ResourceAlreadyExistsException:
            pass
        except Exception as e:
            logger.error(f"Error creating CloudWatch log group: {e}")
            self.enabled = False
            return
            
        # Create log stream if it doesn't exist
        try:
            self.client.create_log_stream(
                logGroupName=log_group,
                logStreamName=stream_name
            )
        except self.client.exceptions.ResourceAlreadyExistsException:
            pass
        except Exception as e:
            logger.error(f"Error creating CloudWatch log stream: {e}")
            self.enabled = False
            return
        
        # Mark initialization as complete
        self.init_done = True
    
    def write(self, message):
        """
        Write a log message to CloudWatch.
        
        This method is called by loguru for each log message.
        
        Args:
            message: The formatted log message
        """
        # Skip if CloudWatch logging is disabled
        if not self.enabled:
            return
        
        # Log initialization success only once
        if self.init_done and not hasattr(self, 'init_logged'):
            self.init_logged = True
            # Don't log this message to CloudWatch to avoid recursion
            print(f"CloudWatch logging initialized for stream: {self.stream_name}")
        
        timestamp = int(time.time() * 1000)  # Milliseconds since epoch
        try:
            kwargs = {
                'logGroupName': self.log_group,
                'logStreamName': self.stream_name,
                'logEvents': [{
                    'timestamp': timestamp,
                    'message': message
                }]
            }
            
            # Include sequence token if we have one
            if self.sequence_token:
                kwargs['sequenceToken'] = self.sequence_token
                
            response = self.client.put_log_events(**kwargs)
            self.sequence_token = response.get('nextSequenceToken')
        except Exception as e:
            # If we get InvalidSequenceTokenException, get the correct token and retry
            if hasattr(e, 'response') and 'InvalidSequenceTokenException' in str(e):
                try:
                    streams = self.client.describe_log_streams(
                        logGroupName=self.log_group,
                        logStreamNamePrefix=self.stream_name
                    )
                    if streams.get('logStreams'):
                        self.sequence_token = streams['logStreams'][0].get('uploadSequenceToken')
                        if self.sequence_token:
                            # Retry with the correct sequence token
                            kwargs['sequenceToken'] = self.sequence_token
                            response = self.client.put_log_events(**kwargs)
                            self.sequence_token = response.get('nextSequenceToken')
                except Exception as e2:
                    # Only log the error at most once per instance
                    if not hasattr(self, 'error_logged'):
                        self.error_logged = True
                        print(f"Error retrieving CloudWatch sequence token: {e2}")
            elif not hasattr(self, 'error_logged'):
                # Only log each error type once to avoid spamming logs
                self.error_logged = True
                print(f"Error sending logs to CloudWatch: {e}")


def setup_cloudwatch_logging():
    """
    Setup CloudWatch logging for the application.
    
    This function initializes CloudWatch logging based on environment variables
    and adds a CloudWatch sink to loguru if credentials are available.
    
    Environment Variables:
        AWS_ACCESS_KEY_ID: AWS access key ID
        AWS_SECRET_ACCESS_KEY: AWS secret access key
        AWS_REGION: AWS region (default: us-east-1)
        CLOUDWATCH_LOG_GROUP: CloudWatch log group name (default: /cinema-chat-bot)
        IDENTIFIER: Unique identifier for the bot instance
    
    Returns:
        bool: True if CloudWatch logging was set up successfully, False otherwise
    """
    # Configure AWS CloudWatch logging if credentials are available
    aws_access_key = os.getenv("AWS_ACCESS_KEY_ID")
    aws_secret_key = os.getenv("AWS_SECRET_ACCESS_KEY")
    aws_region = os.getenv("AWS_REGION", "us-east-1")
    log_group = os.getenv("CLOUDWATCH_LOG_GROUP", "/cinema-chat-bot")
    
    # Define a unique log stream name using the bot identifier or timestamp
    bot_identifier = os.getenv("IDENTIFIER", f"bot-{int(time.time())}")
    log_stream = f"{bot_identifier}-{int(time.time())}"
    #save log_stream name to env variable
    os.environ["LOG_STREAM"] = log_stream
    
    # Setup CloudWatch logging if AWS credentials are provided
    if aws_access_key and aws_secret_key:
        try:
            # Create a boto3 session with AWS credentials
            boto3_session = boto3.Session(
                aws_access_key_id=aws_access_key,
                aws_secret_access_key=aws_secret_key,
                region_name=aws_region
            )
            
            # Create our CloudWatch sink
            cloudwatch_sink = CloudWatchSink(
                session=boto3_session,
                log_group=log_group,
                stream_name=log_stream
            )
            
            # Only add the sink if it was initialized successfully
            if cloudwatch_sink.enabled:
                # Add CloudWatch sink to loguru
                logger.add(
                    cloudwatch_sink.write,
                    level="INFO",  # Use INFO or higher for CloudWatch to reduce costs
                    format="{time:YYYY-MM-DD HH:mm:ss.SSS} - {level} - {name}:{function}:{line} - {message}"
                )
                
                logger.info(f"CloudWatch logging initialized for stream: {log_stream}")
                return True
            else:
                logger.warning("CloudWatch sink creation failed, continuing with console logging only")
                return False
        except Exception as e:
            logger.error(f"Failed to initialize CloudWatch logging: {e}")
            # Continue with only console logging
            return False
    else:
        logger.info("AWS credentials not found, CloudWatch logging disabled")
        return False
