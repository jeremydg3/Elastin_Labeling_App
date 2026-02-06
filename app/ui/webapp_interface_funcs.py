"""
Web App Interface Functions
Functions for communicating with the Google Apps Script web app backend.
"""
import io
import os
import csv
import base64
import numpy as np
import requests
import cv2
import tifffile
from pathlib import Path
from typing import List, Optional, Dict, Any
import hashlib
import time


WEB_APP_URL = "https://script.google.com/macros/s/AKfycbyk9LTgILaUTa-HlSMnz9Ads9neY-lf8Y-giVduiIL7k5Q5mWYKmHtsZreUgPU9TT3aUw/exec"
MAX_ATTEMPTS = 3
CACHE_DIR = Path("cache")
CACHE_DIR.mkdir(exist_ok=True)

def encode_png_b64(tile_rgb: np.ndarray) -> str:
    """
    Encode an RGB tile as a base64-encoded PNG string.
    
    Args:
        tile_rgb: RGB uint8 array (H, W, 3)
    
    Returns:
        Base64-encoded PNG string
    """
    ok, buf = cv2.imencode(".png", cv2.cvtColor(tile_rgb, cv2.COLOR_RGB2BGR))
    if not ok:
        raise RuntimeError("cv2.imencode(.png) failed")
    return base64.b64encode(buf.tobytes()).decode("ascii")


def encode_csv_b64(mask: np.ndarray) -> str:
    """
    Encode a mask array as a base64-encoded CSV string.
    
    Args:
        mask: uint8 array (H, W) with values 0..9 (groups) or 255 (empty)
    
    Returns:
        Base64-encoded CSV string
    """
    s = io.StringIO()
    writer = csv.writer(s, lineterminator="\n")
    # write as integers; faster than savetxt for small tiles
    mask_uint16 = mask.astype(np.uint16)
    for i in range(mask_uint16.shape[0]):
        writer.writerow(mask_uint16[i].tolist())
    text = s.getvalue().encode("utf-8")
    return base64.b64encode(text).decode("ascii")


def _get_cache_path(file_id: str) -> Path:
    """Get cache file path for a given file ID."""
    # Use hash to create safe filename
    safe_id = hashlib.md5(file_id.encode()).hexdigest()
    return CACHE_DIR / f"{safe_id}.tif"


def _save_to_cache(file_id: str, data: bytes) -> None:
    """Save image data to cache."""
    try:
        cache_path = _get_cache_path(file_id)
        cache_path.write_bytes(data)
    except Exception as e:
        # Don't fail if caching fails
        print(f"Cache write failed: {e}")


def _load_from_cache(file_id: str) -> Optional[bytes]:
    """Load image data from cache if available."""
    try:
        cache_path = _get_cache_path(file_id)
        if cache_path.exists():
            return cache_path.read_bytes()
    except Exception as e:
        print(f"Cache read failed: {e}")
    return None


def fetch_next_image(web_app_url: str = WEB_APP_URL, user: Optional[str] = "anonymous", use_cache: bool = True) -> Dict[str, Any]:
    """
    Fetch the next image from the queue.
    
    Args:
        web_app_url: URL of the Google Apps Script web app
        user: Username requesting the image
        use_cache: Whether to use local disk cache (default: True)
    
    Returns:
        Dictionary with either:
        - {"done": True, "message": "Queue empty."}
        - {"done": False, "data": {...}, "fname": "...", "img_array": np.ndarray}
    
    Raises:
        requests.RequestException: If the request fails
        RuntimeError: If image processing fails
    """
    for attempt in range(MAX_ATTEMPTS):
        # Claim next image from queue
        r = requests.post(web_app_url, json={"action": "next", "user": user}, timeout=60)
        r.raise_for_status()
        data = r.json()
        
        if data.get("done"):
            return {"done": True, "message": data.get("message", "Queue empty.")}
        
        file_id = data['fileId']
        fname = data.get("fileName", "(unnamed)")
        
        # Try cache first
        b = None
        if use_cache:
            b = _load_from_cache(file_id)
            if b:
                print(f"Cache hit for {fname}")
        
        # Download if not cached
        if b is None:
            raw_url = f"{web_app_url}?raw={file_id}"
            rb = requests.get(raw_url, timeout=500)
            rb.raise_for_status()
            
            # Decode base64 (Apps Script returns base64 text)
            b64_text = rb.text.strip()
            b = base64.b64decode(b64_text)
            
            # Save to cache for next time
            if use_cache:
                _save_to_cache(file_id, b)
        
        try:
            arr = tifffile.imread(io.BytesIO(b))
        except Exception as e:
            print(f"TIFF read error on attempt {attempt + 1}/{MAX_ATTEMPTS}: {e}")
            if attempt == MAX_ATTEMPTS - 1:
                raise
            continue
        
        return {
            "done": False,
            "data": data,
            "fname": fname,
            "img_array": arr,
        }
    else:
        raise RuntimeError("Failed to fetch next image after multiple attempts.")


def save_tiles_locally(base_name: str,
                      tiles_rgb: List[np.ndarray],
                      masks: List[np.ndarray],
                      orig_indices: Optional[List[int]] = None,
                      output_dir: str = "labeled_tiles") -> None:
    """
    Save tiles and masks locally to disk.
    
    Args:
        base_name: Base name for the files (image title)
        tiles_rgb: List of RGB tile arrays
        masks: List of mask arrays (same length as tiles_rgb)
        orig_indices: Optional list of original tile indices for naming
        output_dir: Directory to save the tiles (default: "labeled_tiles")
    """
    assert len(tiles_rgb) == len(masks), "tiles_rgb and masks must have same length"
    
    # Create output directory structure
    base_path = Path(output_dir)
    images_dir = base_path / "images"
    masks_dir = base_path / "masks"
    
    images_dir.mkdir(parents=True, exist_ok=True)
    masks_dir.mkdir(parents=True, exist_ok=True)
    
    # Save each tile and mask
    for i in range(len(tiles_rgb)):
        i_orig = orig_indices[i] if orig_indices is not None else i
        
        # Save PNG image
        png_path = images_dir / f"{base_name}_tile_{i_orig:04d}.png"
        cv2.imwrite(str(png_path), cv2.cvtColor(tiles_rgb[i], cv2.COLOR_RGB2BGR))
        
        # Save CSV mask
        csv_path = masks_dir / f"{base_name}_tile_{i_orig:04d}.csv"
        np.savetxt(str(csv_path), masks[i], delimiter=",", fmt="%d")


def upload_tiles_batch(base_name: str,
                       tiles_rgb: List[np.ndarray],
                       masks: List[np.ndarray],
                       source_img_fname: Optional[str] = None,
                       orig_indices: Optional[List[int]] = None,
                       author: Optional[str] = "anonymous",
                       web_app_url: str = WEB_APP_URL,
                       save_locally: bool = False,
                       local_output_dir: str = "labeled_tiles") -> Dict[str, Any]:
    """
    Upload tiles and masks to the web app in a single batch request.
    
    Args:
        base_name: Base name for the files (image title)
        tiles_rgb: List of RGB tile arrays
        masks: List of mask arrays (same length as tiles_rgb)
        source_img_fname: Optional source image filename for reference
        orig_indices: Optional list of original tile indices for naming
        author: Username uploading the tiles
        web_app_url: URL of the Google Apps Script web app
        save_locally: Whether to save tiles locally in addition to uploading
        local_output_dir: Directory to save local tiles (default: "labeled_tiles")
    
    Returns:
        Response dictionary from the server
    
    Raises:
        AssertionError: If tiles and masks have different lengths
        RuntimeError: If upload fails
        requests.RequestException: If the request fails
    """
    assert len(tiles_rgb) == len(masks), "tiles_rgb and masks must have same length"
    
    # Save locally if requested
    if save_locally:
        save_tiles_locally(base_name, tiles_rgb, masks, orig_indices, local_output_dir)
    
    batch_size = len(tiles_rgb)
    chunk_size = 5
    upload_results = []
    
    # Upload tiles in chunks of 5 or less
    for chunk_start in range(0, batch_size, chunk_size):
        chunk_end = min(chunk_start + chunk_size, batch_size)
        
        # Build items for this chunk
        items = []
        for i in range(chunk_start, chunk_end):
            i_orig = orig_indices[i] if orig_indices is not None else i
            items.append({
                "i": i_orig,
                "png_b64": encode_png_b64(tiles_rgb[i]),
                "csv_b64": encode_csv_b64(masks[i]),
                "png_name": f"{base_name}_tile_{i_orig:04d}.png",
                "csv_name": f"{base_name}_tile_{i_orig:04d}.csv",
            })

        payload = {
            "action": "upload_tiles",
            "author": author,
            "baseName": base_name,
            "source_img_fname": source_img_fname,
            "items": items,
        }
        
        r = requests.post(web_app_url, json=payload, timeout=3000)
        r.raise_for_status()
        
        try:
            res = r.json()
        except requests.exceptions.HTTPError as e:
            print(f"HTTP error occurred: {e}")
            print(f"Response text: {e.response.text}")
            raise
        except requests.exceptions.JSONDecodeError as e:
            print(f"JSONDecodeError: {e}")
            print(f"Response text that caused the error: {r.text if 'r' in locals() else 'No response available'}")
            raise
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
            raise

        if not res.get("ok"):
            raise RuntimeError(f"Upload failed for chunk {chunk_start}-{chunk_end}: {res}")
        
        upload_results.append(res)
    
    # Return combined result
    return {
        "ok": True,
        "chunks_uploaded": len(upload_results),
        "total_tiles": batch_size,
        "results": upload_results
    }


def skip_image(web_app_url: str = WEB_APP_URL, file_id: Optional[str] = None) -> None:
    """
    Skip the current image in the queue.
    
    Args:
        web_app_url: URL of the Google Apps Script web app
        file_id: ID of the file to skip
    
    Raises:
        requests.RequestException: If the request fails
    """
    requests.post(web_app_url, json={"action": "skip", "fileId": file_id}, timeout=30)


def mark_image_done(web_app_url: str = WEB_APP_URL, file_id: Optional[str] = None) -> None:
    """
    Mark the current image as done in the queue.
    
    Args:
        web_app_url: URL of the Google Apps Script web app
        file_id: ID of the file to mark as done
    
    Raises:
        requests.RequestException: If the request fails
    """
    requests.post(web_app_url, json={"action": "done", "fileId": file_id}, timeout=30)


def get_user_list(web_app_url: str = WEB_APP_URL) -> list:
    """
    Retrieve the list of users from the web app.
    
    Args:
        web_app_url: URL of the Google Apps Script web app 

    Returns:
        List of user dictionaries
    """
    r = requests.post(web_app_url, json={"action": "user_list"}, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("users", [])


def clean_exit(web_app_url: str = WEB_APP_URL, file_id: Optional[str] = None) -> None:
    """
    Notify the web app of a clean exit.
    
    Args:
        web_app_url: URL of the Google Apps Script web app
        file_id: Optional ID of the current file being processed
    """
    try:
        requests.post(web_app_url, json={"action": "clean_exit", "fileId": file_id}, timeout=10)
    except requests.RequestException:
        pass  # Ignore errors on exit


def create_new_user(web_app_url: str = WEB_APP_URL, name: Optional[str] = None) -> bool:
    """
    Create a new user in the web app.
    
    Args:
        web_app_url: URL of the Google Apps Script web app
        name: Name of the new user
    """
    if name is None:
        return False
    r = requests.post(web_app_url, json={"action": "create_user", "name": name}, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("ok", False)


def clean_cache(web_app_url: str = WEB_APP_URL) -> Dict[str, Any]:
    """
    Clean up the cache by removing completed images.
    
    Args:
        web_app_url: URL of the Google Apps Script web app
    
    Returns:
        Dictionary with cleanup statistics
    """
    try:
        # Get list of completed file IDs from backend
        print("Requesting completed IDs from backend...")
        r = requests.post(web_app_url, json={"action": "get_completed_ids"}, timeout=30)
        r.raise_for_status()
        data = r.json()
        
        print(f"Backend response: {data}")
        
        if not data.get("ok"):
            error_msg = data.get("error", "Unknown error")
            return {"ok": False, "message": f"Backend error: {error_msg}"}
        
        completed_ids = data.get("fileIds", [])
        print(f"Found {len(completed_ids)} completed images to clean")
        deleted_count = 0
        
        # Delete cache files for completed images
        for file_id in completed_ids:
            cache_path = _get_cache_path(file_id)
            if cache_path.exists():
                try:
                    cache_path.unlink()
                    deleted_count += 1
                except Exception as e:
                    print(f"Failed to delete cache file {cache_path}: {e}")
        
        return {
            "ok": True,
            "completed_count": len(completed_ids),
            "deleted_count": deleted_count
        }
    except Exception as e:
        print(f"Cache cleanup error: {e}")
        return {"ok": False, "message": str(e)}


def get_cache_stats() -> Dict[str, Any]:
    """
    Get statistics about the cache.
    
    Returns:
        Dictionary with cache size and file count
    """
    try:
        if not CACHE_DIR.exists():
            return {"file_count": 0, "total_size_mb": 0}
        
        files = list(CACHE_DIR.glob("*.tif"))
        total_size = sum(f.stat().st_size for f in files)
        
        return {
            "file_count": len(files),
            "total_size_mb": round(total_size / (1024 * 1024), 2)
        }
    except Exception as e:
        return {"error": str(e)}


def prefetch_next_image(web_app_url: str = WEB_APP_URL) -> None:
    """
    Prefetch the next image in the background to warm the cache.
    This peeks at the next image without claiming it.
    Downloads the file to cache so it's ready when user requests it.
    
    Note: This is a "peek" operation - it doesn't claim the image.
    Call this in a background thread while user works on current image.
    
    Args:
        web_app_url: URL of the Google Apps Script web app
    """
    try:
        # Peek at next image (get file ID without claiming)
        r = requests.post(web_app_url, json={"action": "peek_next"}, timeout=30)
        
        # If peek action doesn't exist in backend, silently skip prefetch
        if r.status_code != 200:
            return
            
        data = r.json()
        if data.get("done") or not data.get("fileId"):
            return
        
        file_id = data['fileId']
        
        # Check if already cached
        if _load_from_cache(file_id) is not None:
            return  # Already cached
        
        # Download and cache
        raw_url = f"{web_app_url}?raw={file_id}"
        rb = requests.get(raw_url, timeout=180)
        rb.raise_for_status()
        
        # Decode and cache
        b = base64.b64decode(rb.content)
        _save_to_cache(file_id, b)
        print(f"Prefetched image {file_id} to cache")
        
    except Exception as e:
        # Silently fail - prefetch is optional optimization
        print(f"Prefetch failed (non-critical): {e}")
