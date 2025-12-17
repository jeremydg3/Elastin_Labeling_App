"""
Web App Interface Functions
Functions for communicating with the Google Apps Script web app backend.
"""
import io
import csv
import base64
import numpy as np
import requests
import cv2
import tifffile
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
        
        # Decode base64 -> numpy via tifffile
        b = base64.b64decode(rb.text)
        arr = tifffile.imread(io.BytesIO(b))
        
        return {
            "done": False,
            "data": data,
            "fname": fname,
            "img_array": arr,
        }
    else:
        raise RuntimeError("Failed to fetch next image after multiple attempts.")


def upload_tiles_batch(base_name: str,
                       tiles_rgb: List[np.ndarray],
                       masks: List[np.ndarray],
                       source_img_fname: Optional[str] = None,
                       orig_indices: Optional[List[int]] = None,
                       author: Optional[str] = "anonymous",
                       web_app_url: str = WEB_APP_URL) -> Dict[str, Any]:
    """
    Upload tiles and masks to the web app in a single batch request.
    
    Args:
        base_name: Base name for the files (image title)
        tiles_rgb: List of RGB tile arrays
        masks: List of mask arrays (same length as tiles_rgb)
        source_img_fname: Optional source image filename for reference
        orig_indices: Optional list of original tile indices for naming
        web_app_url: URL of the Google Apps Script web app
    
    Returns:
        Response dictionary from the server
    
    Raises:
        AssertionError: If tiles and masks have different lengths
        RuntimeError: If upload fails
        requests.RequestException: If the request fails
    """
    assert len(tiles_rgb) == len(masks), "tiles_rgb and masks must have same length"
    batch_size = len(tiles_rgb)

    items = []
    for i in range(batch_size):
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
    
    r = requests.post(web_app_url, json=payload, timeout=300)
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
        raise RuntimeError(f"Upload failed: {res}")
    
    return res


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
