"""Configuration for Cinema-Chat MCP Server."""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """MCP Server configuration settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )

    # GoodCLIPS API
    goodclips_api_url: str = "http://localhost:8080"
    goodclips_api_key: Optional[str] = None

    # Video Configuration
    videos_path: str = "/data/videos"
    video_output_device: Optional[str] = None  # e.g., "/dev/video0" or display number

    # Search defaults
    default_search_limit: int = 5
    max_search_limit: int = 20

    # MCP Server
    server_name: str = "cinema-chat-video"
    server_version: str = "0.1.0"

    # Logging
    log_level: str = "INFO"


settings = Settings()
