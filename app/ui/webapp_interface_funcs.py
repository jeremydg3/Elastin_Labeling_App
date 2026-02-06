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


WEB_APP_URL = "https://script.google.com/macros/s/AKfycbw8mQLmfC5dYQ2Hc41M3d-nTKsxx_oRsgIl_c6iFdpkeoerrrI1OaoIJdbCSkoHPNHDSg/exec"
MAX_ATTEMPTS = 3

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


def fetch_next_image(web_app_url: str = WEB_APP_URL, user: Optional[str] = "anonymous") -> Dict[str, Any]:
    """
    Fetch the next image from the queue.
    
    Args:
        web_app_url: URL of the Google Apps Script web app
        user: Username requesting the image
    
    Returns:
        Dictionary with either:
        - {"done": True, "message": "Queue empty."}
        - {"done": False, "data": {...}, "fname": "...", "img_array": np.ndarray}
    
    Raises:
        requests.RequestException: If the request fails
        RuntimeError: If image processing fails
    """
    for _ in range(MAX_ATTEMPTS):
        # Claim next image from queue
        r = requests.post(web_app_url, json={"action": "next", "user": user}, timeout=60)
        r.raise_for_status()
        data = r.json()
        
        if data.get("done"):
            return {"done": True, "message": data.get("message", "Queue empty.")}
        
        # Fetch the raw image bytes
        fname = data.get("fileName", "(unnamed)")
        raw_url = f"{web_app_url}?raw={data['fileId']}"
        rb = requests.get(raw_url, timeout=120)
        rb.raise_for_status()
        
        # Decode base64 (Apps Script always returns base64 over HTTP)
        b = base64.b64decode(rb.content)
        arr = tifffile.imread(io.BytesIO(b))
        
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
