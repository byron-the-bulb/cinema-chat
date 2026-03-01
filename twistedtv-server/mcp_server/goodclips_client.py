"""Client for GoodCLIPS API."""
import httpx
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)


class SceneResult(BaseModel):
    """Result from scene search."""
    id: int
    uuid: str
    video_id: int
    scene_index: int
    start_time: float
    end_time: float
    duration: float
    has_captions: bool
    caption_count: int
    distance: float


class DialogResult(BaseModel):
    """Result from dialog search (/api/v1/search/text).

    clip_start/clip_end are the dialog caption boundaries ± 0.5s pad —
    use these (not scene start_time/end_time) when calling play_clip.
    """
    video_id: int
    scene_index: int
    clip_start: float   # first caption start_time - pad
    clip_end: float     # last caption end_time + pad
    dialog_text: str    # spoken lines matched in this scene
    distance: float


class GoodCLIPSClient:
    """Client for interacting with GoodCLIPS API."""

    def __init__(self, base_url: str, api_key: Optional[str] = None):
        """Initialize GoodCLIPS client.

        Args:
            base_url: Base URL for GoodCLIPS API (e.g., http://localhost:8080)
            api_key: Optional API key for authentication
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.client = httpx.AsyncClient(timeout=30.0)

    async def search_semantic(
        self,
        query: str,
        limit: int = 5,
        video_ids: Optional[List[int]] = None
    ) -> List[SceneResult]:
        """Search for scenes using semantic text search.

        Args:
            query: Text description to search for (e.g., "a person nodding")
            limit: Maximum number of results to return
            video_ids: Optional list of video IDs to filter results

        Returns:
            List of scene results ordered by similarity

        Raises:
            httpx.HTTPError: If the API request fails
        """
        url = f"{self.base_url}/api/v1/search/semantic"

        payload = {
            "query": query,
            "limit": limit
        }

        if video_ids:
            payload["video_ids"] = video_ids

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        logger.info(f"Searching for: '{query}' (limit={limit})")

        response = await self.client.post(url, json=payload, headers=headers)
        response.raise_for_status()

        data = response.json()
        results = []

        for item in data.get("results", []):
            scene_data = item.get("scene", {})
            scene_data["distance"] = item.get("distance", 0.0)
            results.append(SceneResult(**scene_data))

        logger.info(f"Found {len(results)} scenes")
        return results

    async def search_dialog(
        self,
        query: str,
        limit: int = 5,
        video_ids: Optional[List[int]] = None,
    ) -> List[DialogResult]:
        """Search for scenes by spoken dialog similarity.

        Embeds the query and finds scenes where characters say something
        semantically similar. Returns clip_start/clip_end tight around the
        actual dialog (not the full scene), ready to pass to play_clip.

        Args:
            query: Text to match against spoken dialog (e.g. a bot reply)
            limit: Maximum number of results
            video_ids: Optional list of video IDs to restrict search

        Returns:
            List of DialogResult ordered by similarity (closest first)
        """
        url = f"{self.base_url}/api/v1/search/text"
        payload: dict = {"query": query, "limit": limit}
        if video_ids:
            payload["video_ids"] = video_ids

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        logger.info(f"Dialog search: '{query}' (limit={limit})")
        response = await self.client.post(url, json=payload, headers=headers)
        response.raise_for_status()

        data = response.json()
        results = []
        for item in data.get("results", []):
            scene = item.get("scene", {})
            results.append(DialogResult(
                video_id=scene["video_id"],
                scene_index=scene["scene_index"],
                clip_start=item["clip_start"],
                clip_end=item["clip_end"],
                dialog_text=item.get("dialog_text", ""),
                distance=item.get("distance", 0.0),
            ))

        logger.info(f"Found {len(results)} dialog matches")
        return results

    async def get_video_path(self, video_id: int) -> Optional[str]:
        """Get the file path for a video.

        Args:
            video_id: ID of the video

        Returns:
            File path to the video, or None if not found
        """
        url = f"{self.base_url}/api/v1/videos/{video_id}"

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = await self.client.get(url, headers=headers)
            response.raise_for_status()

            data = response.json()
            video_data = data.get("video", {})
            return video_data.get("filepath")
        except httpx.HTTPError as e:
            logger.error(f"Failed to get video {video_id}: {e}")
            return None

    async def get_stats(self) -> Dict[str, Any]:
        """Get GoodCLIPS database statistics.

        Returns:
            Dictionary with stats (video count, scene count, etc.)
        """
        url = f"{self.base_url}/api/v1/stats"

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        response = await self.client.get(url, headers=headers)
        response.raise_for_status()

        return response.json()

    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()

    async def __aenter__(self):
        """Context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        await self.close()
